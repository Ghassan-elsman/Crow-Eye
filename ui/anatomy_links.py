"""Where each artifact table is explained, and how to get there.

An examiner reading a table of Shellbags rows has no route from the row in
front of them to what that row actually is. Eye-Describe holds that
explanation, and every section of every anatomy page is addressable by a
fragment - so a table can point at the section that discusses its own records
rather than at the top of a page and a scroll.

Only tables a page genuinely documents appear here. SRUM, browser history,
firewall rules and the rest have no anatomy page yet, and a button that landed
on a directory instead of an explanation would teach an examiner to stop
trusting the button.

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
        "shellbags_anatomy", "what-they-are",
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
    "UserAssist_table": (
        "registry_anatomy", "userassist",
        "What UserAssist counts, and the ROT13 that hides it from a keyword "
        "search"),
    "Bam_table": (
        "registry_anatomy", "bam-dam",
        "BAM and DAM: per-user last-run times kept by the kernel itself"),
    "Dam_table": (
        "registry_anatomy", "bam-dam",
        "BAM and DAM: per-user last-run times kept by the kernel itself"),
    "MUICache_table": (
        "registry_anatomy", "what-ran",
        "Where MUICache sits among the execution artifacts, and what it does "
        "not prove"),

    "RecentDocs_table": (
        "registry_anatomy", "user-activity",
        "Where a user went, and the MRU order that is the only record of "
        "sequence"),
    "TypedPath_table": (
        "registry_anatomy", "user-activity",
        "Paths typed into the Explorer bar, most recent first"),
    "OpenSaveMRU_table": (
        "registry_anatomy", "user-activity",
        "What a file dialog opened or saved, and which program hosted it"),
    "LastSaveMRU_table": (
        "registry_anatomy", "user-activity",
        "Which executable last used a file dialog, and in which folder"),
    "RunMRU_table": (
        "registry_anatomy", "user-activity",
        "Commands typed into the Run box"),
    "WordWheelQuery_table": (
        "registry_anatomy", "user-activity",
        "Search terms typed into the Explorer search bar"),

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
        "registry_anatomy", "usb-devices",
        "Which volumes this user actually opened, as opposed to which the "
        "machine saw"),

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
}


def url_for(attr):
    """The full URL for a table, or None when nothing documents it."""
    entry = ANATOMY_LINKS.get(attr)
    if not entry:
        return None
    page, anchor, _tip = entry
    return BASE_URL + page + ("#" + anchor if anchor else "")


def tooltip_for(attr):
    """What the reader will find there, or None."""
    entry = ANATOMY_LINKS.get(attr)
    return entry[2] if entry else None
