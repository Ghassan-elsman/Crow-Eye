"""Extractor registry — maps the 'extractor' field of behavior_rules.json
onto the Python implementations."""

from uba.engine.extractors import logs as _logs
from uba.engine.extractors import artifacts as _artifacts
from uba.engine.extractors import files as _files

# name -> callable(ctx, rules) -> list[BehaviorEvent]
# 'rules' is the list of rule dicts sharing that extractor (most extractors
# have exactly one; usn_file_activity serves five file-operation rules).
EXTRACTORS = {
    "sessions_logon": _logs.sessions_logon,
    "sessions_logoff": _logs.sessions_logoff,
    "sessions_unlock": _logs.sessions_unlock,
    "process_creation_4688": _logs.process_creation_4688,
    "service_installed": _logs.service_installed,
    "boot_shutdown": _logs.boot_shutdown,
    "time_changed": _logs.time_changed,
    "log_cleared": _logs.log_cleared,
    "privileged_logon": _logs.privileged_logon,
    "explicit_credentials": _logs.explicit_credentials,
    "account_enumeration": _logs.account_enumeration,
    "account_management": _logs.account_management,
    "app_error": _logs.app_error,
    "service_state_changed": _logs.service_state_changed,
    "windows_update": _logs.windows_update,
    "userassist_launch": _artifacts.userassist_launch,
    "prefetch_execution": _artifacts.prefetch_execution,
    "shimcache_presence": _artifacts.shimcache_presence,
    "amcache_file_presence": _artifacts.amcache_file_presence,
    "srum_network_sessions": _artifacts.srum_network_sessions,
    "device_present": _artifacts.device_present,
    "app_install": _artifacts.app_install,
    "shellbags_browsing": _artifacts.shellbags_browsing,
    "network_share_access": _artifacts.network_share_access,
    "file_open_artifacts": _artifacts.file_open_artifacts,
    "usb_devices": _artifacts.usb_devices,
    "browser_history": _artifacts.browser_history,
    "local_search": _artifacts.local_search,
    "srum_foreground": _artifacts.srum_foreground,
    "srum_network": _artifacts.srum_network,
    "network_profiles": _artifacts.network_profiles,
    "driver_binaries": _artifacts.driver_binaries,
    "autostart_programs": _artifacts.autostart_programs,
    "autostart_service": _artifacts.autostart_service,
    "usn_file_activity": _files.usn_file_activity,
    "file_copy_inferred": _files.file_copy_inferred,
}
