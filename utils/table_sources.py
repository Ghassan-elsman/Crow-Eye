"""Which GUI table comes from which artifact / database / SQLite table - and
why an empty one is empty.

There was no single map of this before: the registry tabs live in
`_populate_registry_tables`'s `table_mapping`, Browser and AmCache tabs are
named by convention, everything else is hard-coded in its loader. This module
is that map, plus `explain_empty()`, which the i button above every empty
table calls.

REGISTRY_TABLE_WIDGETS must equal the `table_mapping` literal in
`Crow Eye.py::_populate_registry_tables` - `test_table_sources_complete.py`
compares the two, so a tab added there and not here fails a test rather than
getting no i button in silence.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from utils.parse_status import (ARTIFACTS, NOT_A_FAILURE, ArtifactOutcome,
                                ParseStatus, ParseStatusStore, artifact_label,
                                db_table_counts, status_label)


# sqlite table -> widget attribute (registry_data.db)
REGISTRY_TABLE_WIDGETS: Dict[str, str] = {
    "computer_Name": "computerName_table",
    "time_zone": "TimeZone_table",
    "TimeZoneInfo": "TimeZoneInfo_table",
    "network_interfaces": "NetworkInterface_table",
    "NetworkInterfacesInfo": "NetworkInterfacesInfo_table",
    "NetworkProfiles": "NetworkProfiles_table",
    "Network_list": "NetworkLists_table",
    "SystemServices": "SystemServices_table",
    "ScheduledTasks": "ScheduledTasks_table",
    "winlogon": "winlogon_table",
    "image_file_execution_options": "image_file_execution_options_table",
    "appinit_dlls": "appinit_dlls_table",
    "appcert_dlls": "appcert_dlls_table",
    "active_setup": "active_setup_table",
    "run_services": "run_services_table",
    "run_services_once": "run_services_once_table",
    "policies_explorer_run": "policies_explorer_run_table",
    "user_shell_folders": "user_shell_folders_table",
    "lsa_packages": "lsa_packages_table",
    "boot_execute": "boot_execute_table",
    "clsid_inprocserver32": "clsid_inprocserver32_table",
    "UserAccounts": "UserAccounts_table",
    "ComputerNameInfo": "ComputerNameInfo_table",
    "SecurityPosture": "SecurityPosture_table",
    "DefenderExclusions": "DefenderExclusions_table",
    "FirewallRules": "FirewallRules_table",
    "NetworkShares": "NetworkShares_table",
    "ConnectedDevices": "ConnectedDevices_table",
    "MountPoints2": "MountPoints2_table",
    "RDPClientMRU": "RDPClientMRU_table",
    "OfficeDocuments": "OfficeDocuments_table",
    "FeatureUsage": "FeatureUsage_table",
    "CompatibilityAssistant": "CompatibilityAssistant_table",
    "RecentApps": "RecentApps_table",
    "ApplicationArtifacts": "ApplicationArtifacts_table",
    "shutdown_information": "ShutdownRaw_table",
    "Windows_lastupdate_subkeys": "LastUpdateSubkeys_table",
    "registry_hive_state": "RegistryHiveState_table",
    "registry_class_names": "RegistryClassNames_table",
    "registry_security_descriptors": "RegistrySecurity_table",
    "registry_carved_keys": "RegistryCarvedKeys_table",
    "registry_carved_values": "RegistryCarvedValues_table",
    "registry_value_changes": "RegistryValueChanges_table",
    "registry_key_times": "RegistryKeyTimes_table",
    "startup_approved": "StartupApproved_table",
    "app_paths": "AppPaths_table",
    "safe_boot_services": "SafeBootServices_table",
    "zone_map": "ZoneMap_table",
    "app_permissions": "AppPermissions_table",
    "shared_dlls": "SharedDlls_table",
    "hid_devices": "HidDevices_table",
    "network_cards": "NetworkCards_table",
    "system_configuration": "SystemConfiguration_table",
    "AutoStartPrograms": "AutoStartPrograms_table",
    "machine_run": "MachineRun_table",
    "machine_run_once": "MachineRunOnce_table",
    "user_run": "UserRun_table",
    "user_run_once": "UserRunOnce_table",
    "RunMRU": "RunMRU_table",
    "Windows_lastupdate": "LastUpdate_table",
    "WindowsUpdateInfo": "LastUpdateInfo_table",
    "ShutdownInfo": "ShutDown_table",
    "BrowserHistory": "RegistryBrowserHistory_table",
    "USBDevices": "USBDevices_table",
    "USBInstances": "USBInstances_table",
    "USBProperties": "USBProperties_table",
    "USBStorageDevices": "USBStorageDevices_table",
    "USBStorageVolumes": "USBStorageVolumes_table",
    "RecentDocs": "RecentDocs_table",
    "OpenSaveMRU": "OpenSaveMRU_table",
    "LastSaveMRU": "LastSaveMRU_table",
    "TypedPaths": "TypedPath_table",
    "BAM": "Bam_table",
    "DAM": "Dam_table",
    "InstalledSoftware": "tableWidget",
    "Shellbags": "Shellbags_table",
    "UserAssist": "UserAssist_table",
    "MUICache": "MUICache_table",
    "WordWheelQuery": "WordWheelQuery_table",
    "UserProfiles": "UserProfiles_table",
    "local_groups": "local_groups_table",
    "lsa_policy": "lsa_policy_table",
    "audit_policy": "audit_policy_table",
    "lsa_secrets": "lsa_secrets_table",
    "cached_domain_logons": "cached_domain_logons_table",
    "command_processor": "command_processor_table",
    "drivers32": "drivers32_table",
    "shell_service_object_delay_load": "shell_service_object_delay_load_table",
    "browser_helper_objects": "browser_helper_objects_table",
    "shared_task_scheduler": "shared_task_scheduler_table",
    "shell_icon_overlay_identifiers": "shell_icon_overlay_identifiers_table",
    "credential_providers": "credential_providers_table",
    "netsh_helper_dlls": "netsh_helper_dlls_table",
    "amsi_providers": "amsi_providers_table",
    "security_providers": "security_providers_table",
    "print_monitors": "print_monitors_table",
    "print_processors": "print_processors_table",
    "network_providers": "network_providers_table",
    "wmi_autorecover_mofs": "wmi_autorecover_mofs_table",
    "windows_load_run": "windows_load_run_table",
    "shell_open_command": "shell_open_command_table",
    "file_exts": "file_exts_table",
    "cid_size_mru": "cid_size_mru_table",
    "programs_cache": "programs_cache_table",
    "regedit_lastkey": "regedit_lastkey_table",
    "printer_connections": "printer_connections_table",
    "explorer_advanced": "explorer_advanced_table",
    "rdp_tcp": "rdp_tcp_table",
    "usbstor_start": "usbstor_start_table",
    "windows_script_host": "windows_script_host_table",
    "dnscache_parameters": "dnscache_parameters_table",
    "files_not_to_snapshot": "files_not_to_snapshot_table",
    "winevt_channels": "winevt_channels_table",
    "wpdbusenum": "wpdbusenum_table",
    "device_classes": "device_classes_table",
    "volume_info_cache": "volume_info_cache_table",
    "machine_guid": "machine_guid_table",
    "product_options": "product_options_table",
    "os_install_history": "os_install_history_table",
    "active_computer_name": "active_computer_name_table",
    "hivelist": "hivelist_table",
    "system_environment": "system_environment_table",
    "network_adapters": "network_adapters_table",
    "group_policy_history": "group_policy_history_table",
}

# widget attribute -> (artifact, db file, sqlite table), for everything that
# is not registry / AmCache / Browser.
_STATIC_SOURCES: Dict[str, Tuple[str, str, str]] = {
    "LNK_table": ("lnk_jumplist", "LnkDB.db", "LNK_Files"),
    "AJL_table": ("lnk_jumplist", "LnkDB.db", "Automatic_JumpLists"),
    "Clj_table": ("lnk_jumplist", "LnkDB.db", "Custom_JumpLists"),
    "Prefetch_table": ("prefetch", "prefetch_data.db", "prefetch_data"),
    "SystemLogs_table": ("evtx", "Log_Claw.db", "SystemLogs"),
    "AppLogs_table": ("evtx", "Log_Claw.db", "ApplicationLogs"),
    "SecurityLogs_table": ("evtx", "Log_Claw.db", "SecurityLogs"),
    "ShimCache_main_table": ("shimcache", "shimcache.db", "shimcache_entries"),
    "RecycleBin_main_table": ("recyclebin", "recyclebin_analysis.db", "recycle_bin_entries"),
    "SRUM_application_usage_table": ("srum", "srum_data.db", "srum_application_usage"),
    "SRUM_network_connectivity_table": ("srum", "srum_data.db", "srum_network_connectivity"),
    "SRUM_network_data_table": ("srum", "srum_data.db", "srum_network_data_usage"),
    "SRUM_energy_usage_table": ("srum", "srum_data.db", "srum_energy_usage"),
    "SRUM_app_timeline_table": ("srum", "srum_data.db", "srum_app_timeline"),
    "MFT_table": ("mft", "mft_claw_analysis.db", "mft_records"),
    "MFT_standard_info_table": ("mft", "mft_claw_analysis.db", "mft_standard_info"),
    "MFT_file_names_table": ("mft", "mft_claw_analysis.db", "mft_file_names"),
    "MFT_data_attributes_table": ("mft", "mft_claw_analysis.db", "mft_data_attributes"),
    "USN_table": ("usn", "USN_journal.db", "journal_events"),
    "Correlated_table": ("mft_usn_correlation", "mft_usn_correlated_analysis.db",
                         "mft_usn_correlated"),
}


def build_table_sources(amcache_tables: Iterable[str] = (),
                        browser_tables: Iterable[str] = ()) -> Dict[str, Tuple[str, str, str]]:
    """widget attribute -> (artifact, db file, sqlite table) for every GUI table.

    AmCache tabs are built from AMCACHE_SCHEMAS and Browser tabs from
    BROWSER_TABS at runtime, so their names are passed in.
    """
    sources = dict(_STATIC_SOURCES)
    for table, attr in REGISTRY_TABLE_WIDGETS.items():
        sources[attr] = ("registry", "registry_data.db", table)
    for table in amcache_tables:
        sources["Amcache_%s_table" % table] = ("amcache", "amcache.db", table)
    for table in browser_tables:
        short = table.replace("browser_", "", 1)
        sources["Browser_%s_table" % short] = ("browser", "browser_analysis.db", table)
    return sources


# --------------------------------------------------------------------------
# Hints: why a table can be legitimately empty (rules as data)
# --------------------------------------------------------------------------

_HINTS_CACHE: Optional[Dict[str, str]] = None


def _hints_path() -> Optional[str]:
    roots = []
    base = getattr(sys, "_MEIPASS", None)
    if base:
        roots.append(base)
    roots.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for root in roots:
        p = os.path.join(root, "configs", "empty_table_hints.json")
        if os.path.isfile(p):
            return p
    return None


def load_hints() -> Dict[str, str]:
    global _HINTS_CACHE
    if _HINTS_CACHE is None:
        hints: Dict[str, str] = {}
        path = _hints_path()
        if path:
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                for key, val in (data.get("tables") or {}).items():
                    if isinstance(val, str):
                        hints[key.lower()] = val
                for key, val in (data.get("artifacts") or {}).items():
                    if isinstance(val, str):
                        hints["@" + key.lower()] = val
            except (OSError, ValueError):
                pass
        _HINTS_CACHE = hints
    return _HINTS_CACHE


def hint_for(sqlite_table: str, artifact: str = "") -> str:
    hints = load_hints()
    return hints.get((sqlite_table or "").lower()) or hints.get("@" + (artifact or "").lower(), "")


# --------------------------------------------------------------------------
# Explaining an empty table
# --------------------------------------------------------------------------

@dataclass
class EmptyReason:
    widget_attr: str
    artifact: str
    db_file: str
    sqlite_table: str
    status: str              # a ParseStatus value, or DISPLAY_ERROR
    headline: str
    explanation: str
    hint: str = ""
    db_rows: Optional[int] = None
    outcome: Optional[ArtifactOutcome] = None
    sources: List[dict] = field(default_factory=list)

    @property
    def is_failure(self) -> bool:
        return self.status not in NOT_A_FAILURE and self.status != ParseStatus.PARSED \
            and self.status != ParseStatus.NOT_RUN

    @property
    def tooltip(self) -> str:
        return "Why is this table empty? - %s" % self.headline


DISPLAY_ERROR = "DISPLAY_ERROR"


def explain_empty(widget_attr: str, case_root: Optional[str],
                  sources: Dict[str, Tuple[str, str, str]],
                  store: Optional[ParseStatusStore] = None,
                  _db_counts_cache: Optional[Dict[str, Dict[str, int]]] = None) -> Optional[EmptyReason]:
    """Why `widget_attr` shows no rows. None when the table is not mapped."""
    src = sources.get(widget_attr)
    if not src:
        return None
    artifact, db_file, table = src
    label = artifact_label(artifact)
    hint = hint_for(table, artifact)

    db_path = os.path.join(case_root or "", "Target_Artifacts", db_file) if case_root else ""
    if _db_counts_cache is not None and db_path in _db_counts_cache:
        counts = _db_counts_cache[db_path]
    else:
        counts = db_table_counts(db_path) if db_path else {}
        if _db_counts_cache is not None:
            _db_counts_cache[db_path] = counts
    db_exists = bool(db_path) and os.path.isfile(db_path)
    rows = counts.get(table)

    if store is None and case_root:
        store = ParseStatusStore(case_root)
    outcome = store.outcome_for(artifact) if store is not None else None

    def reason(status, headline, explanation):
        return EmptyReason(widget_attr, artifact, db_file, table, status, headline,
                           explanation, hint, rows, outcome,
                           list(outcome.sources_checked) if outcome else [])

    # 4. The database has rows and the table shows none: a display problem,
    #    not an evidence one - checked first because it overrides everything.
    if rows is not None and rows > 0:
        return reason(DISPLAY_ERROR, "Display/load error",
                      "The database holds %d row(s) in '%s', but none were loaded into "
                      "this table. This is a Crow-Eye display problem, not missing "
                      "evidence - check Settings -> Logs (crow_eye.log / console.log)."
                      % (rows, table))

    # 1. The artifact itself did not parse cleanly: that is the reason.
    if outcome is not None and outcome.status != ParseStatus.PARSED:
        if outcome.status == ParseStatus.PARTIAL and rows == 0:
            return reason(ParseStatus.NO_RECORDS,
                          "%s partially parsed - nothing of this type" % label,
                          "%s\n\nThis particular table received no rows." % outcome.message)
        return reason(outcome.status, "%s: %s" % (label, status_label(outcome.status)),
                      outcome.message or "")

    if outcome is None:
        # 5. No parse status recorded (case parsed before this feature, or
        #    never parsed): reason from the database alone and say so.
        if not db_exists:
            return reason(ParseStatus.NOT_RUN, "%s has not been parsed" % label,
                          "No %s database exists in this case and no parse status was "
                          "recorded. Run the %s parser (live, offline or image) to fill "
                          "this table." % (db_file, label))
        if rows is None:
            return reason(ParseStatus.UNSUPPORTED_FORMAT,
                          "Table not produced by the parser",
                          "%s exists but has no '%s' table. No parse status was recorded "
                          "for this case, so the cause cannot be confirmed - re-parse to "
                          "get one." % (db_file, table))
        return reason(ParseStatus.NO_RECORDS, "Parsed - no records of this type",
                      "'%s' exists in %s with 0 rows. (This case has no recorded parse "
                      "status; re-parsing records one.)" % (table, db_file))

    # Artifact PARSED from here on.
    # 2. ... but this table was never created.
    if rows is None:
        return reason(ParseStatus.NO_RECORDS if hint else ParseStatus.UNSUPPORTED_FORMAT,
                      "Parsed - this table was not produced",
                      "%s parsed successfully (%d record(s) overall), but did not create "
                      "the '%s' table. The source format/version on this evidence does "
                      "not carry this data, or the parser path that writes it was not "
                      "reached." % (label, outcome.records, table))

    # 3. Table exists with 0 rows: the evidence simply has none.
    return reason(ParseStatus.NO_RECORDS, "Parsed - no records of this type",
                  "%s parsed successfully (%d record(s) overall), but the evidence holds "
                  "no '%s' entries. This is normal for a machine where this activity or "
                  "setting never occurred. Not a failure." % (label, outcome.records, table))
