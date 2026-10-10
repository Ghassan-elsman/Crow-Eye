"""Where each artifact table is explained, and how to get there.

An examiner reading a table of Shellbags rows has no route from the row in
front of them to what that row actually is. Eye-Describe holds that
explanation, and every section of every anatomy page is addressable by a
fragment - so a table can point at the section that discusses its own records
rather than at the top of a page and a scroll.

Only tables a page genuinely documents appear here. Browser history, firewall
rules and the rest have no anatomy page yet, and a button that landed on a
directory instead of an explanation would teach an examiner to stop trusting the
button.

The anchors are a contract with the site. `test_anatomy_links_resolve.py`
checks every one of them against the pages themselves whenever the site tree
is beside the engine, because a section renamed over there would otherwise
break a button over here with nothing to say so.
"""

BASE_URL = "https://crow-eye.com/Eye-Describe/"

# widget attribute on the main window -> (page, anchor, what is over there)
#
# The third field is the tooltip. It says what the reader will find, not what
# the button does - "Open the page" is what a button obviously does, and the
# examiner is deciding whether it is worth the click.
ANATOMY_LINKS = {
    # --- artifacts with a page of their own --------------------------------
    "Shellbags_table": (
        "shell-items-shellbags-anatomy", "what-they-are",
        "What a shell item is, byte by byte - and why a bag records a view "
        "rather than a person"),
    "ShimCache_main_table": (
        "shimcache_anatomy", "one-record",
        "One AppCompatCache record, field by field - and why it is not proof "
        "of execution"),
    "Prefetch_table": (
        "prefetch_anatomy", "dissection",
        "The .pf format field by field: the files it touched, the volumes, "
        "and the last eight run times"),
    "LNK_table": (
        "lnk_anatomy", "dissection",
        "The shortcut format field by field - target path, MAC times, volume "
        "serial and MFT reference"),
    "AJL_table": (
        "automatic_jumplist", "destlist",
        "The DestList stream: what an application opened, in access order"),
    "Clj_table": (
        "custom_jumplist", "dissection",
        "How a custom destinations file is framed, and why it has no "
        "DestList"),
    "USN_table": (
        "usn_anatomy", "dissection",
        "One USN record field by field, and what each reason code means"),
    # The correlated table joins each USN record to its MFT entry through the
    # record's file reference - the field this section dissects.
    "Correlated_table": (
        "usn_anatomy", "dissection",
        "One USN record field by field - the reason codes, and the file "
        "reference that ties each record to its MFT entry"),

    # --- SRUM: one tab per provider table, each its own section --------------
    "SRUM_application_usage_table": (
        "srum_anatomy", "tbl-application-usage",
        "The Application Resource Usage columns field by field - the CPU and "
        "disk cost of running, per app, per hour"),
    "SRUM_network_data_table": (
        "srum_anatomy", "tbl-network-data",
        "Bytes sent and received per app, per interface - the cleanest "
        "data-exfiltration signal SRUM carries"),
    "SRUM_network_connectivity_table": (
        "srum_anatomy", "tbl-network-connectivity",
        "When an interface was connected and for how long - placing a machine "
        "on a network at a time"),
    "SRUM_energy_usage_table": (
        "srum_anatomy", "tbl-energy",
        "Battery charge and power-state columns, and why they are mostly "
        "populated on laptops"),
    "SRUM_app_timeline_table": (
        "srum_anatomy", "tbl-app-timeline",
        "Focus, keyboard and mouse seconds - the provider that shows a human "
        "was present, and the only one carrying hosted services"),

    # --- the MFT, one tab per attribute ------------------------------------
    "MFT_table": (
        "mft_anatomy", "record",
        "A 1024-byte FILE record, byte by byte"),
    "MFT_standard_info_table": (
        "mft_anatomy", "standard-information-flags",
        "$STANDARD_INFORMATION and its flags - the times timestomping usually "
        "reaches first"),
    "MFT_file_names_table": (
        "mft_anatomy", "file-name-namespaces",
        "$FILE_NAME, its namespaces, and the second set of times that is far "
        "harder to change"),
    "MFT_data_attributes_table": (
        "mft_anatomy", "data-attributes",
        "How $DATA is stored, resident and non-resident"),

    # --- AmCache: built at runtime from the hive's own schema ---------------
    "Amcache_InventoryApplication_table": (
        "amcache_anatomy", "hive-records",
        "What an AmCache entry is made of, and why presence is not execution"),
    "Amcache_InventoryApplicationFile_table": (
        "amcache_anatomy", "hive-records",
        "The file inventory records, field by field, including the SHA-1 that "
        "is not quite a SHA-1"),
    "Amcache_InventoryApplicationShortcut_table": (
        "amcache_anatomy", "hive-records",
        "The shortcut inventory, and the AUMID it shares with Jump Lists"),
    "Amcache_InventoryDriverBinary_table": (
        "amcache_anatomy", "hive-records",
        "Driver binaries as the Appraiser recorded them"),
    "Amcache_InventoryDriverPackage_table": (
        "amcache_anatomy", "hive-records",
        "Driver packages as the Appraiser recorded them"),

    # --- registry artifacts, documented as sections -------------------------
    # --- user activity: one section per table ------------------------------
    # Every table the User Activity dashboard reads has its own section, so
    # the button lands on THIS table's key, value format, timestamp and
    # caveats - not on a page-wide overview the examiner then has to search.
    "UserAssist_table": (
        "registry_anatomy", "table-userassist",
        "UserAssist: the 72-byte record, the ROT13 names, run and focus "
        "counts, and what it cannot see"),
    "Bam_table": (
        "registry_anatomy", "table-bam",
        "BAM: the kernel's last-run time per program and SID, and why a "
        "device path is not a drive letter"),
    "Dam_table": (
        "registry_anatomy", "table-dam",
        "DAM: BAM's twin on Modern Standby devices - and why it is empty on "
        "most desktops"),
    "MUICache_table": (
        "registry_anatomy", "table-muicache",
        "MUICache: friendly names the shell read from programs it handled, "
        "with no time of their own"),
    "RecentApps_table": (
        "registry_anatomy", "table-recentapps",
        "RecentApps: early Windows 10's record of apps used and the files "
        "they opened"),
    "FeatureUsage_table": (
        "registry_anatomy", "table-featureusage",
        "FeatureUsage: taskbar counters per program, and the one key time "
        "they share"),
    "CompatibilityAssistant_table": (
        "registry_anatomy", "table-compatibility-assistant",
        "The Program Compatibility Assistant store: programs this user ran, "
        "kept after the file is gone"),
    "file_exts_table": (
        "registry_anatomy", "table-file-exts",
        "FileExts: which programs opened each file type, and the default the "
        "user chose"),
    "programs_cache_table": (
        "registry_anatomy", "table-programs-cache",
        "StartPage2 ProgramsCache: the Start menu's cached program list"),
    "regedit_lastkey_table": (
        "registry_anatomy", "table-regedit-lastkey",
        "Registry Editor's last key and favourites"),
    "RegistryBrowserHistory_table": (
        "registry_anatomy", "table-typed-urls",
        "TypedURLs and TypedURLsTime: addresses typed into the address bar"),
    "RDPClientMRU_table": (
        "registry_anatomy", "table-rdp-client-mru",
        "Remote Desktop hosts this user connected to, and the account hint"),
    "OfficeDocuments_table": (
        "registry_anatomy", "table-office-mru",
        "Office File and Place MRUs, and the Trusted Documents that record "
        "Enable Content"),
    "ApplicationArtifacts_table": (
        "registry_anatomy", "table-application-mrus",
        "What PuTTY, WinSCP, WinRAR, 7-Zip and others remember"),
    "AppPermissions_table": (
        "registry_anatomy", "table-app-permissions",
        "Camera, microphone and location use per app, with start and stop "
        "times"),

    "RecentDocs_table": (
        "shell-items-shellbags-anatomy", "table-recentdocs",
        "RecentDocs: per-extension MRUs, the order in MRUListEx, and the one "
        "time each key keeps"),
    "TypedPath_table": (
        "shell-items-shellbags-anatomy", "table-typedpaths",
        "TypedPaths: paths typed into the Explorer bar, url1 the newest"),
    "OpenSaveMRU_table": (
        "shell-items-shellbags-anatomy", "table-opensavemru",
        "OpenSavePidlMRU: files chosen in Open and Save dialogs"),
    "LastSaveMRU_table": (
        "shell-items-shellbags-anatomy", "table-lastsavemru",
        "LastVisitedPidlMRU: which program used a dialog, and in which folder"),
    "RunMRU_table": (
        "shell-items-shellbags-anatomy", "table-runmru",
        "RunMRU: commands typed into the Run box, ordered by MRUList"),
    "WordWheelQuery_table": (
        "shell-items-shellbags-anatomy", "table-wordwheelquery",
        "WordWheelQuery: terms typed into the Explorer search box"),
    "cid_size_mru_table": (
        "shell-items-shellbags-anatomy", "table-cidsizemru",
        "CIDSizeMRU: programs that opened a common dialog - no path at all"),
    "SystemConfiguration_table": (
        "shell-items-shellbags-anatomy", "table-taskband",
        "Taskband (one row of this table): the items pinned to the taskbar"),
    "user_shell_folders_table": (
        "shell-items-shellbags-anatomy", "table-user-shell-folders",
        "User Shell Folders: where Desktop, Documents and Downloads really "
        "point"),
    "shell_open_command_table": (
        "shell-items-shellbags-anatomy", "table-shell-extensions",
        "shell\\open\\command: what runs when a file type is opened"),
    "shell_icon_overlay_identifiers_table": (
        "shell-items-shellbags-anatomy", "table-shell-extensions",
        "Icon overlay handlers: DLLs Explorer loads for every folder view"),
    "shell_service_object_delay_load_table": (
        "shell-items-shellbags-anatomy", "table-shell-extensions",
        "ShellServiceObjectDelayLoad: objects Explorer loads at start"),

    "USBDevices_table": (
        "registry_anatomy", "usb-devices",
        "What the registry records about an attached device, and the "
        "connection times it will not give up"),
    "USBInstances_table": (
        "registry_anatomy", "usb-devices",
        "Per-instance device records, and how they tie to a drive letter"),
    "USBProperties_table": (
        "registry_anatomy", "usb-devices",
        "The Properties subkey - and why it denies even an elevated "
        "administrator through the API"),
    "USBStorageDevices_table": (
        "registry_anatomy", "usb-devices",
        "USBSTOR: vendor, product and serial for every device ever attached"),
    "USBStorageVolumes_table": (
        "registry_anatomy", "usb-devices",
        "Volumes on removable media, and how MountedDevices ties them to "
        "letters"),
    "MountPoints2_table": (
        "shell-items-shellbags-anatomy", "table-mountpoints2",
        "MountPoints2 and Map Network Drive MRU: which volumes and shares "
        "this user mounted"),

    "AutoStartPrograms_table": (
        "registry_anatomy", "persistence",
        "What is scheduled to run again - persistence, which is not execution"),
    "MachineRun_table": (
        "registry_anatomy", "persistence",
        "Machine-wide Run keys, and what persistence does and does not prove"),
    "UserRun_table": (
        "registry_anatomy", "persistence",
        "Per-user Run keys, and what persistence does and does not prove"),
    "MachineRunOnce_table": (
        "registry_anatomy", "persistence",
        "RunOnce, which deletes its own value as it runs"),
    "UserRunOnce_table": (
        "registry_anatomy", "persistence",
        "RunOnce, which deletes its own value as it runs"),
    "run_services_table": (
        "registry_anatomy", "persistence",
        "The RunServices keys, and where they sit among the ASEPs"),
    "ScheduledTasks_table": (
        "registry_anatomy", "persistence",
        "TaskCache: what the scheduler will run, and when it last did"),
    "SystemServices_table": (
        "registry_anatomy", "persistence",
        "Services, their start types, and the image each one loads"),
    "StartupApproved_table": (
        "registry_anatomy", "persistence",
        "Which autostart entries are actually enabled, and which are switched "
        "off"),
    "winlogon_table": (
        "registry_anatomy", "persistence",
        "The Winlogon hooks, and the value names that are routinely "
        "mis-spelled in the literature"),
    "image_file_execution_options_table": (
        "registry_anatomy", "persistence",
        "IFEO: a debugger entry that runs a different program than the one "
        "launched"),
    "appinit_dlls_table": (
        "registry_anatomy", "persistence",
        "AppInit_DLLs, loaded into every process that links user32"),
    "active_setup_table": (
        "registry_anatomy", "persistence",
        "Active Setup, which runs once per user at logon"),

    # --- the hive itself ---------------------------------------------------
    "RegistryHiveState_table": (
        "registry-internals", "logs",
        "Whether the hive was stale when it was read, and what the "
        "transaction logs were still holding"),
    "RegistryValueChanges_table": (
        "registry-internals", "logs",
        "What the .LOG1 and .LOG2 files held that the hive on disk did not"),
    "RegistryCarvedKeys_table": (
        "registry-internals", "carving",
        "What carving recovers from freed cells, and what it cannot"),
    "RegistryCarvedValues_table": (
        "registry-internals", "carving",
        "What carving recovers from freed cells, and what it cannot"),
    "RegistrySecurity_table": (
        "registry-internals", "security",
        "sk records: the security descriptors hundreds of keys share"),
    "hivelist_table": (
        "registry-internals", "hives",
        "Which hive files exist, and which of them a reader must open"),

    # Browser forensics. The tab is built from BROWSER_TABS, and each table is
    # also set as Browser_<name>_table so these resolve.
    "Browser_history_table": (
        "browser-forensics", "navigation",
        "How a visit is recorded, and what the transition type separates - a "
        "typed URL from a redirect"),
    "Browser_gecko_history_table": (
        "browser-forensics", "navigation",
        "Firefox visits: moz_places and moz_historyvisits, and how PRTime "
        "differs from Chromium's epoch"),
    "Browser_shortcuts_table": (
        "browser-forensics", "navigation",
        "What the user actually typed into the omnibox - intent, even for a "
        "site that was never opened"),
    "Browser_downloads_table": (
        "browser-forensics", "navigation",
        "What landed on disk, from where, and whether the browser flagged it"),
    "Browser_cookies_table": (
        "browser-forensics", "identity",
        "Cookie lifetimes, and why the value is ciphertext rather than text"),
    "Browser_credentials_table": (
        "browser-forensics", "crypto",
        "The key chain behind a saved password, and what has to be preserved "
        "to decrypt one later"),
    "Browser_cache_table": (
        "browser-forensics", "anatomy",
        "The blockfile cache byte by byte - the index, the cache address and "
        "the EntryStore record a status code comes from"),
    "Browser_service_worker_table": (
        "browser-forensics", "anatomy",
        "CacheStorage metadata: a protobuf stored after the body, not an "
        "HTTP response head"),
    "Browser_sessions_table": (
        "browser-forensics", "sessions",
        "SNSS session records, and the two commands that say which window and "
        "tab a navigation belonged to"),
    "Browser_local_storage_table": (
        "browser-forensics", "webapp",
        "LevelDB, including the write-ahead log that still holds deleted keys"),
    "Browser_indexeddb_table": (
        "browser-forensics", "webapp",
        "The IndexedDB key prefix, and how object stores are named"),
    "Browser_search_engines_table": (
        "browser-forensics", "providers",
        "Which providers a profile knows, and which one was the default"),
    "Browser_dips_table": (
        "browser-forensics", "tracking",
        "Bounce-tracking interaction and storage times"),
    "Browser_network_state_table": (
        "browser-forensics", "tracking",
        "Alt-Svc, HSTS and Reporting/NEL - sites contacted with no history row"),
    "Browser_metadata_table": (
        "browser-forensics", "crypto",
        "The DPAPI-wrapped master key, the scheme label, and the browser build "
        "that last wrote the profile"),
}


def url_for(attr):
    """The full URL for a table, or None when nothing documents it."""
    entry = ANATOMY_LINKS.get(attr)
    if not entry:
        return None
    page, anchor, _tip = entry
    return BASE_URL + page + ("#" + anchor if anchor else "")


def _bundle_roots():
    """Where docs/anatomy can be: inside a frozen build, then beside the source."""
    import os
    import sys
    roots = []
    base = getattr(sys, "_MEIPASS", None)
    if base:
        roots.append(base)
    roots.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return [os.path.join(r, "docs", "anatomy", "Eye-Describe") for r in roots]


def local_page_for(attr):
    """(file path, anchor) of the copy bundled with the app, or None.

    scripts/sync_anatomy_pages.py copies every page this map points at into
    docs/anatomy, so a button works on a workstation with no internet - which
    is most of the ones Crow-Eye runs on.
    """
    import os
    entry = ANATOMY_LINKS.get(attr)
    if not entry:
        return None
    page, anchor, _tip = entry
    for root in _bundle_roots():
        path = os.path.join(root, page + ".html")
        if os.path.isfile(path):
            return path, anchor
    return None


def tooltip_for(attr):
    """What the reader will find there, or None."""
    entry = ANATOMY_LINKS.get(attr)
    return entry[2] if entry else None
