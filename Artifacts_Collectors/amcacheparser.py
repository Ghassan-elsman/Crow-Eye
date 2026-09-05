# Amcache parser to extract data from Amcache.hve and store in a normalized SQLite database.
# Modified to:
# - Store all subkey data, including unrecognized subkeys in an UnknownSubkeys table.
# - Handle duplicates by adding entries with a UTC timestamp (parsed_at) instead of updating.

# - Add processing indicators for user feedback.
# - Compare data as JSON for DeviceCensus/UnknownSubkeys and text for other fields.
# Original author: Maxim Suhanov

import ctypes
import os
from platform import system, version
import sys
from Registry import Registry
import sqlite3
import hashlib
import shutil
import tempfile
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
from utils.time_utils import (get_current_forensic_timestamp,
                              format_forensic_timestamp,
                              filetime_to_datetime)
try:
    from Artifacts_Collectors import registry_transaction_log
except ImportError:                                   # pragma: no cover
    import registry_transaction_log
try:
    from Artifacts_Collectors import registry_hive_walk
except ImportError:                                   # pragma: no cover
    import registry_hive_walk
try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False

# Configuration variables
LIVE_ANALYSIS = True  # Set to True for live analysis, False for offline analysis
# Note: LIVE_AMCACHE_PATH is now constructed dynamically based on windows_partition parameter
# Default offline path (can be overridden)
OFFLINE_AMCACHE_PATH = r"E:\Crow Eye research\Amcache.hve"  # Path for offline Amcache.hve
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
NORMALIZED_DATABASE_PATH = os.path.join(SCRIPT_DIR, r"Amcashedb.db")  # Normalized database path
SEARCH_KEYS = None  # Set to None for all keys or a list like ["Root\\InventoryApplication"]

def get_live_amcache_path(windows_partition: str = "C:") -> str:
    """
    Get the live Amcache.hve path based on Windows partition.
    
    Args:
        windows_partition: Windows partition letter (e.g., "C:", "D:")
        
    Returns:
        str: Full path to Amcache.hve
    """
    return f"{windows_partition}\\Windows\\AppCompat\\Programs\\Amcache.hve"

# Schema for normalized database tables (name after id if present, parsed_at last)
# Every column below is a registry value name that was OBSERVED in a real
# Amcache.hve, not a guess. The comment above each table is how many entries
# that subkey held on the reference system.
#
# key_last_write is the KEY's own LastWriteTime: when the Compatibility
# Appraiser WROTE the entry. It was captured nowhere before - `parsed_at` is
# when Crow-Eye ran, which belongs on no timeline - but it is not an event
# time either, and how much ordering it supports differs per table because the
# Appraiser writes in batches. Measured on the reference system: all 373 Mare
# entries share ONE timestamp, 90% of 445 driver binaries share one, 92% of
# 292 PnP devices share one, while InventoryApplicationFile has 1,086 distinct
# times across 5,212 rows. It bounds "seen by".
#
# Two subkeys are deliberately NOT given fixed columns:
#
#   DeviceCensus carries 237 distinct value names across 16 entries, and
#   Windows adds more every release, so a fixed column list is stale on
#   arrival. It uses the name/value shape below instead - wider than one
#   column of JSON, which is what it used to be, and queryable:
#   WHERE name = 'AADDeviceId'.
#
#   Nine further subkeys exist in the hive but were EMPTY on every system
#   available here, so their columns cannot be verified against real data.
#   They get the same shape rather than a column list somebody invented.
#
# Anything Microsoft adds next still lands in UnknownSubkeys.
# --------------------------------------------------------------- timestamps
#
# AmCache writes its dates as locale-formatted TEXT, in at least three shapes,
# and stores them next to values that are not dates at all. Sorted as text they
# order wrongly, and read by eye they are ambiguous. Each is normalised into a
# companion `<column>_utc`; the original string is never overwritten, because
# it is what the artifact actually says.
#
# WHICH FORMAT, decided by counting rather than by assuming. Across this
# machine's hive, the second component exceeds 12 hundreds of times and the
# first essentially never - so these are MM/DD/YYYY:
#
#     install_date  msi_install_date  first_install_date  link_date
#     driver_ver_date  driver_last_write_time
#
# with exactly one counter-example: InventoryApplication.install_date for
# Discord reads "20/12/2026", written by that application's own installer. So
# the rule below is forced where the value forces it and defaults only where
# the value genuinely cannot say.
AMCACHE_HASH_LIMIT = 31_457_280      # 30 MiB - see FileId below

# Text dates, normalised by _parse_amcache_date.
AMCACHE_DATE_COLUMNS = {
    "InventoryApplication": ["install_date", "msi_install_date"],
    "InventoryApplicationFile": ["link_date"],
    "InventoryDevicePnp": ["install_date", "first_install_date",
                           "driver_ver_date"],
    "InventoryDriverBinary": ["driver_last_write_time"],
    "InventoryDriverPackage": ["date"],
}

# Whole numbers of seconds since 1970. InventoryDriverBinary.DriverTimeStamp is
# the PE header's TimeDateStamp, which is frequently randomised by modern
# toolchains - a value outside a sane range is left NULL rather than turned
# into a date somewhere in 2069.
AMCACHE_EPOCH_COLUMNS = {
    "InventoryDriverBinary": ["driver_time_stamp"],
}

_DATE_SEP = re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})"
                       r"(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?\s*$")
_DATE_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})"
                       r"(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?\s*$")


# A normalised timestamp is a claim that something happened then, so a value
# that cannot be such a claim is left out of the normalised column rather than
# dressed up as one. Two real cases on this machine, both in `link_date`:
#
#   01/01/1970  epoch zero - 467 of 2408 entries. It means the PE carries NO
#               link date, which is normal for Go, Rust and reproducible
#               builds (Docker, bzip2, Claude Setup all read this way).
#               Normalising it would put 400+ files at the same instant and
#               invent a cluster that is not there.
#   2105-11-16  a randomised TimeDateStamp, which modern toolchains emit.
#
# The other five date columns have nothing outside this window, so it costs
# no real data. The raw string is kept either way.
_PLAUSIBLE_FROM = datetime(1990, 1, 1)
_PLAUSIBLE_UNTIL_YEARS = 1


_PLAUSIBLE_UNTIL = None


def _plausible_upper_bound():
    """Now plus a year, computed once. NAIVE UTC, like every other timestamp
    in the engine - a single tz-aware datetime compared against naive ones
    raises, and it is the kind of thing that empties a whole feather."""
    global _PLAUSIBLE_UNTIL
    if _PLAUSIBLE_UNTIL is None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        _PLAUSIBLE_UNTIL = now.replace(year=now.year + _PLAUSIBLE_UNTIL_YEARS)
    return _PLAUSIBLE_UNTIL


def _is_plausible(when):
    if when is None:
        return False
    return _PLAUSIBLE_FROM <= when <= _plausible_upper_bound()


def _parse_amcache_date(text):
    """One of AmCache's text dates as a naive UTC datetime, or None.

    Returns None rather than guessing. `link_date` holds version strings on
    some rows - "2.3.8.0", "1.0.9188" - because the hive itself puts them
    there, and a normaliser that raised on those would take the whole parse
    down with it.
    """
    if text is None:
        return None
    text = str(text).strip()
    if not text:
        return None

    m = _DATE_ISO.match(text)
    if m:                                     # InventoryDriverPackage: 2025-12-2
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hh, mm, ss = (int(m.group(4) or 0), int(m.group(5) or 0),
                      int(m.group(6) or 0))
        try:
            return _plausible_or_none(datetime(y, mo, d, hh, mm, ss))
        except ValueError:
            return None

    m = _DATE_SEP.match(text)
    if not m:
        return None
    a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hh, mm, ss = (int(m.group(4) or 0), int(m.group(5) or 0),
                  int(m.group(6) or 0))

    if b > 12 and a <= 12:
        month, day = a, b                     # forced MM/DD
    elif a > 12 and b <= 12:
        month, day = b, a                     # forced DD/MM - the Discord case
    elif a > 12 and b > 12:
        return None                           # neither reading works
    else:
        month, day = a, b                     # ambiguous; Windows writes MM/DD
    try:
        return _plausible_or_none(datetime(y, month, day, hh, mm, ss))
    except ValueError:
        return None


def _plausible_or_none(when):
    return when if _is_plausible(when) else None


def _parse_amcache_epoch(text):
    """Seconds since 1970 as a naive UTC datetime, or None if implausible."""
    if text is None:
        return None
    try:
        seconds = int(str(text).strip())
    except (TypeError, ValueError):
        return None
    # 1990-01-01 .. 2038-01-19. A PE TimeDateStamp outside that is a randomised
    # or corrupt value, not a date, and is not worth pretending about.
    if not (631152000 <= seconds <= 2147483647):
        return None
    try:
        return _plausible_or_none(datetime(1970, 1, 1) + timedelta(seconds=seconds))
    except (OverflowError, OSError, ValueError):
        return None


# Written out literally in AMCACHE_SCHEMAS below rather than referenced,
# because Sentinel's extract-schema.js reads that dict as source text and
# only understands a literal list - a name referenced there is a table it
# never sees, and the CI gate stays green while ten tables go missing from
# the fleet schema. Kept here as the definition the code compares against.
NAME_VALUE_COLUMNS = ["entry", "name", "value", "key_last_write", "parsed_at"]

# Subkeys stored one row per registry value rather than one row per entry.
NAME_VALUE_TABLES = {
    "DeviceCensus",
    "DriverPackageExtended",
    "InventoryAcpiPhatHealthRecord",
    "InventoryAcpiPhatVersionElement",
    "InventoryApplicationAppV",
    "InventoryApplicationDriver",
    "InventoryApplicationFramework",
    "InventoryDevicePci",
    "InventoryDeviceSensor",
    "InventoryMiscellaneousWAMAccounts",
}

AMCACHE_SCHEMAS = {
    # 380 entries on the reference system
    "InventoryApplication": [
        "program_id", "name", "version", "publisher", "language", "source",
        "root_dir_path", "default_value", "program_instance_id",
        "store_app_type", "inbox_modern_app", "manifest_path",
        "package_full_name", "install_date", "hidden_arp",
        "uninstall_string", "registry_key_path", "msi_package_code",
        "msi_product_code", "msi_install_date", "bundle_manifest_path",
        "user_sid", "install_date_utc", "msi_install_date_utc",
        "key_last_write", "parsed_at"],
    # 5212 entries on the reference system
    "InventoryApplicationFile": [
        "program_id", "file_id", "lower_case_long_path", "name",
        "binary_type", "link_date", "size", "language", "usn",
        "bin_file_version", "bin_product_version", "product_version",
        "version", "product_name", "publisher", "original_file_name",
        "appx_package_full_name", "is_os_component",
        "appx_package_relative_id", "link_date_utc", "file_id_is_partial",
        "file_id_verified", "program_association", "key_last_write",
        "parsed_at"],
    # 129 entries on the reference system
    "InventoryApplicationShortcut": [
        "shortcut_path", "shortcut_target_path", "shortcut_aumid",
        "shortcut_program_id", "default_value", "key_last_write",
        "parsed_at"],
    # 16 entries on the reference system
    "InventoryDeviceContainer": [
        "model_name", "icon", "friendly_name", "model_number",
        "manufacturer", "model_id", "primary_category", "categories",
        "is_machine_container", "discovery_method", "is_connected",
        "is_active", "is_paired", "is_networked", "state", "default_value",
        "key_last_write", "parsed_at"],
    # 1 entries on the reference system
    "InventoryDeviceInterface": [
        "accelerometer3_d", "activity_detection", "ambient_light",
        "barometer", "custom", "floor_elevation",
        "geomagnetic_orientation", "gravity_vector", "gyrometer3_d",
        "humidity", "linear_accelerometer", "magnetometer3_d",
        "orientation", "pedometer", "proximity", "relative_orientation",
        "simple_device_orientation", "temperature", "energy_meter",
        "hinge_angle", "presence_capabilities", "key_last_write",
        "parsed_at"],
    # 8 entries on the reference system
    "InventoryDeviceMediaClass": [
        "audio_render_driver", "audio_capture_driver", "key_last_write",
        "parsed_at"],
    # 292 entries on the reference system
    "InventoryDevicePnp": [
        "model", "manufacturer", "driver_name", "parent_id", "matching_id",
        "class", "class_guid", "description", "enumerator", "service",
        "install_state", "device_state", "inf", "driver_ver_date",
        "install_date", "first_install_date", "driver_package_strong_name",
        "driver_ver_version", "container_id", "problem_code", "provider",
        "driver_id", "bus_reported_description", "hwid", "extended_infs",
        "compid", "stackid", "upper_class_filters", "lower_class_filters",
        "upper_filters", "lower_filters", "device_interface_classes",
        "location_paths", "default_value", "install_date_utc",
        "first_install_date_utc", "driver_ver_date_utc", "key_last_write",
        "parsed_at"],
    # 1 entries on the reference system
    "InventoryDeviceUsbHubClass": [
        "total_user_connectable_ports",
        "total_user_connectable_type_cports", "key_last_write",
        "parsed_at"],
    # 445 entries on the reference system
    "InventoryDriverBinary": [
        "driver_name", "inf", "driver_version", "product",
        "product_version", "wdf_version", "driver_company",
        "driver_package_strong_name", "service", "driver_in_box",
        "driver_signed", "driver_is_kernel_mode", "driver_id",
        "driver_last_write_time", "driver_type", "driver_time_stamp",
        "driver_check_sum", "image_size", "default_value",
        "driver_last_write_time_utc", "driver_time_stamp_utc",
        "key_last_write", "parsed_at"],
    # 80 entries on the reference system
    "InventoryDriverPackage": [
        "class_guid", "class", "directory", "date", "version", "provider",
        "submission_id", "driver_in_box", "inf", "flight_ids",
        "recovery_ids", "is_active", "hwids", "sysfile", "date_utc",
        "key_last_write", "parsed_at"],
    # 25 entries on the reference system
    "InventoryMiscellaneous": [
        "exists", "value", "key_last_write", "parsed_at"],
    # 1 entries on the reference system
    "InventoryMiscellaneousMemorySlotArrayInfo": [
        "slot", "type", "type_details", "speed", "capacity", "model",
        "manufacturer", "total_width", "data_width",
        "memory_error_correction", "default_value", "key_last_write",
        "parsed_at"],
    # 12 entries on the reference system
    "InventoryMiscellaneousUser": [
        "original_name", "exists", "value", "user_id",
        "standard_user_hash", "key_last_write", "parsed_at"],
    # 28 entries on the reference system
    "InventoryMiscellaneousUupInfo": [
        "identifier", "version", "source", "previous_version",
        "last_activated_version", "default_value", "key_last_write",
        "parsed_at"],
    # 373 entries on the reference system
    "Mare": [
        "flags", "default_value", "restore", "root_dir_path", "sdbentryguid",
        "path", "program_id", "far", "key_last_write", "parsed_at"],
    # 85 entries on the reference system
    "MareBackupApps": [
        "hash", "sid_state", "default_value", "key_last_write",
        "parsed_at"],
    "DeviceCensus": [
        "entry", "name", "value", "key_last_write", "parsed_at"],
    "DriverPackageExtended": [
        "entry", "name", "value", "key_last_write", "parsed_at"],
    "InventoryAcpiPhatHealthRecord": [
        "entry", "name", "value", "key_last_write", "parsed_at"],
    "InventoryAcpiPhatVersionElement": [
        "entry", "name", "value", "key_last_write", "parsed_at"],
    "InventoryApplicationAppV": [
        "entry", "name", "value", "key_last_write", "parsed_at"],
    "InventoryApplicationDriver": [
        "entry", "name", "value", "key_last_write", "parsed_at"],
    "InventoryApplicationFramework": [
        "entry", "name", "value", "key_last_write", "parsed_at"],
    "InventoryDevicePci": [
        "entry", "name", "value", "key_last_write", "parsed_at"],
    "InventoryDeviceSensor": [
        "entry", "name", "value", "key_last_write", "parsed_at"],
    "InventoryMiscellaneousWAMAccounts": [
        "entry", "name", "value", "key_last_write", "parsed_at"],
    # Recovered from FREE SPACE, not from the tree - entries deleted from
    # the hive that no tree walker can reach. Same shape as Regclaw's
    # registry_carved_keys / registry_carved_values so the two artifacts read
    # alike. `record_state` is always "deleted"; these are not live entries and
    # must never be mistaken for them.
    "AmcacheCarvedKeys": [
        "cell_offset", "key_name", "key_path", "parent_resolved",
        "key_last_write", "subkey_count", "value_count", "record_state",
        "parsed_at"],
    "AmcacheCarvedValues": [
        "cell_offset", "parent_cell_offset", "key_path", "value_name",
        "value_type", "data_size", "is_inline", "data", "record_state",
        "parsed_at"],

    # The catch-all: a Root subkey Windows adds that nothing here knows about.
    "UnknownSubkeys": ["subkey_name", "data", "key_last_write", "parsed_at"],
}

# Windows API constants
_TOKEN_ADJUST_PRIVILEGES = 0x20
_SE_PRIVILEGE_ENABLED = 0x2
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_CREATE_ALWAYS = 2
_FILE_ATTRIBUTE_NORMAL = 0x80
_FILE_ATTRIBUTE_TEMPORARY = 0x100
_FILE_FLAG_DELETE_ON_CLOSE = 0x04000000
_FILE_SHARE_READ = 1
_FILE_SHARE_WRITE = 2
_FILE_SHARE_DELETE = 4
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_KEY_READ = 0x20019
_KEY_WOW64_64KEY = 0x100
_STATUS_INVALID_PARAMETER = ctypes.c_int32(0xC000000D).value
_REG_NO_COMPRESSION = 4
_ERROR_ACCESS_DENIED = 5
# Open a key using SeBackupPrivilege rather than its DACL - the only way to
# reach HKLM\SECURITY, whose root key grants SYSTEM alone.
_REG_OPTION_BACKUP_RESTORE = 0x00000004
_REG_CREATED_NEW_KEY = 1
_INVALID_SET_FILE_POINTER = 0xFFFFFFFF
_HKEY_USERS = 0x80000003
_HKEY_LOCAL_MACHINE = 0x80000002

# Windows API structures
class _LUID(ctypes.Structure):
    _fields_ = [('LowPart', ctypes.c_uint32), ('HighPart', ctypes.c_int32)]

class _LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [('Luid', _LUID), ('Attributes', ctypes.c_uint32)]

class _TOKEN_PRIVILEGES_5(ctypes.Structure):
    _fields_ = [('PrivilegeCount', ctypes.c_uint32), ('Privilege0', _LUID_AND_ATTRIBUTES),
                ('Privilege1', _LUID_AND_ATTRIBUTES), ('Privilege2', _LUID_AND_ATTRIBUTES),
                ('Privilege3', _LUID_AND_ATTRIBUTES), ('Privilege4', _LUID_AND_ATTRIBUTES)]

# Windows API function definitions
import os

if os.name == 'nt':
    ctypes.windll.kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    ctypes.windll.kernel32.GetCurrentProcess.argtypes = []
    ctypes.windll.advapi32.LookupPrivilegeValueW.restype = ctypes.c_int32
    ctypes.windll.advapi32.LookupPrivilegeValueW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_void_p]
    ctypes.windll.advapi32.OpenProcessToken.restype = ctypes.c_int32
    ctypes.windll.advapi32.OpenProcessToken.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
    ctypes.windll.advapi32.AdjustTokenPrivileges.restype = ctypes.c_int32
    ctypes.windll.advapi32.AdjustTokenPrivileges.argtypes = [ctypes.c_void_p, ctypes.c_int32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p]
    ctypes.windll.kernel32.GetLastError.restype = ctypes.c_uint32
    ctypes.windll.kernel32.GetLastError.argtypes = []
    ctypes.windll.kernel32.CloseHandle.restype = ctypes.c_int32
    ctypes.windll.kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    ctypes.windll.kernel32.CreateFileW.restype = ctypes.c_void_p
    ctypes.windll.kernel32.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    ctypes.windll.advapi32.RegOpenKeyExW.restype = ctypes.c_int32
    ctypes.windll.advapi32.RegOpenKeyExW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    ctypes.windll.advapi32.RegCloseKey.restype = ctypes.c_int32
    ctypes.windll.advapi32.RegCloseKey.argtypes = [ctypes.c_void_p]
    ctypes.windll.advapi32.RegOpenCurrentUser.restype = ctypes.c_int32
    ctypes.windll.advapi32.RegOpenCurrentUser.argtypes = [ctypes.c_uint32, ctypes.c_void_p]

    _APP_HIVES_SUPPORTED = hasattr(ctypes.windll.advapi32, 'RegLoadAppKeyW')
    if _APP_HIVES_SUPPORTED:
        ctypes.windll.advapi32.RegLoadAppKeyW.restype = ctypes.c_int32
        ctypes.windll.advapi32.RegLoadAppKeyW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32]

    ctypes.windll.ntdll.NtSaveKeyEx.restype = ctypes.c_int32
    ctypes.windll.ntdll.NtSaveKeyEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32]
    ctypes.windll.kernel32.GetTempFileNameA.restype = ctypes.c_uint32
    ctypes.windll.kernel32.GetTempFileNameA.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_void_p]
    ctypes.windll.kernel32.SetFilePointer.restype = ctypes.c_uint32
    ctypes.windll.kernel32.SetFilePointer.argtypes = [ctypes.c_void_p, ctypes.c_int32, ctypes.c_void_p, ctypes.c_uint32]
    ctypes.windll.kernel32.ReadFile.restype = ctypes.c_int32
    ctypes.windll.kernel32.ReadFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p]

# File-like object for handling Windows file handles
class NTFileLikeObject(object):
    def __init__(self, handle):
        self.handle = handle
        self.max_size = self.seek(0, 2)
        self.seek(0, 0)

    def seek(self, offset, whence=0):
        offset = ctypes.windll.kernel32.SetFilePointer(self.handle, offset, None, whence)
        if offset == _INVALID_SET_FILE_POINTER:
            raise OSError('The SetFilePointer() routine failed')
        return offset

    def tell(self):
        return self.seek(0, 1)

    def read(self, size=None):
        if size is None or size < 0:
            size = self.max_size - self.tell()
        if size <= 0:
            return b''
        buffer = ctypes.create_string_buffer(size)
        size_out = ctypes.c_uint32()
        result = ctypes.windll.kernel32.ReadFile(self.handle, ctypes.byref(buffer), size, ctypes.byref(size_out), None)
        if result == 0:
            last_error = ctypes.windll.kernel32.GetLastError()
            raise OSError('The ReadFile() routine failed with this status: {}'.format(last_error))
        return buffer.raw[:size_out.value]

    def close(self):
        ctypes.windll.kernel32.CloseHandle(self.handle)

# Class for accessing live registry hives
class RegistryHivesLive(object):
    def __init__(self):
        self._src_handle = None
        self._dst_handle = None
        self._hkcu_handle = None
        self._lookup_process_handle_and_backup_privilege()
        self._acquire_backup_privilege()

    def _lookup_process_handle_and_backup_privilege(self):
        self._proc = ctypes.windll.kernel32.GetCurrentProcess()
        self._backup_luid = _LUID()
        result = ctypes.windll.advapi32.LookupPrivilegeValueW(None, 'SeBackupPrivilege', ctypes.byref(self._backup_luid))
        if result == 0:
            raise OSError('The LookupPrivilegeValueW() routine failed to resolve the \'SeBackupPrivilege\' name')

    def _acquire_backup_privilege(self):
        handle = ctypes.c_void_p()
        result = ctypes.windll.advapi32.OpenProcessToken(self._proc, _TOKEN_ADJUST_PRIVILEGES, ctypes.byref(handle))
        if result == 0:
            raise OSError('The OpenProcessToken() routine failed to provide the TOKEN_ADJUST_PRIVILEGES access')
        tp = _TOKEN_PRIVILEGES_5()
        tp.PrivilegeCount = 1
        tp.Privilege0 = _LUID_AND_ATTRIBUTES()
        tp.Privilege0.Luid = self._backup_luid
        tp.Privilege0.Attributes = _SE_PRIVILEGE_ENABLED
        result_1 = ctypes.windll.advapi32.AdjustTokenPrivileges(handle, False, ctypes.byref(tp), 0, None, None)
        result_2 = ctypes.windll.kernel32.GetLastError()
        if result_1 == 0 or result_2 != 0:
            ctypes.windll.kernel32.CloseHandle(handle)
            raise OSError('The AdjustTokenPrivileges() routine failed to set the backup privilege')
        ctypes.windll.kernel32.CloseHandle(handle)

    def _create_destination_handle(self, FilePath):
        if FilePath is None:
            file_attr = _FILE_ATTRIBUTE_TEMPORARY | _FILE_FLAG_DELETE_ON_CLOSE
            FilePath = self._temp_file()
        else:
            file_attr = _FILE_ATTRIBUTE_NORMAL
        handle = ctypes.windll.kernel32.CreateFileW(FilePath, _GENERIC_READ | _GENERIC_WRITE, _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE, None, _CREATE_ALWAYS, file_attr, None)
        if handle == _INVALID_HANDLE_VALUE:
            raise OSError('The CreateFileW() routine failed to create a file')
        self._dst_handle = handle
        return FilePath

    def _close_destination_handle(self):
        ctypes.windll.kernel32.CloseHandle(self._dst_handle)
        self._dst_handle = None

    def _open_root_key(self, PredefinedKey, KeyPath, WOW64=False):
        handle = ctypes.c_void_p()
        if not WOW64:
            access_rights = _KEY_READ
        else:
            access_rights = _KEY_READ | _KEY_WOW64_64KEY
        result = ctypes.windll.advapi32.RegOpenKeyExW(PredefinedKey, KeyPath, 0, access_rights, ctypes.byref(handle))
        if result == _ERROR_ACCESS_DENIED:
            # RegOpenKeyExW honours the DACL, and HKLM\SECURITY grants only
            # SYSTEM on its ROOT key - so an elevated administrator gets no
            # handle at all and there is nothing for NtSaveKeyEx to save. HKLM
            # \SAM differs: its root opens and only the children are blocked,
            # which is why SAM has worked here all along and SECURITY did not.
            #
            # REG_OPTION_BACKUP_RESTORE asks the kernel to authorise the open
            # with SeBackupPrivilege instead of the DACL - already held by
            # _acquire_backup_privilege above. This is how `reg save` reaches
            # the same key. RegCreateKeyExW is the call that accepts the flag;
            # on an existing key it opens rather than creates, and the
            # disposition it reports back says which happened.
            disposition = ctypes.c_ulong()
            result = ctypes.windll.advapi32.RegCreateKeyExW(
                PredefinedKey, KeyPath, 0, None, _REG_OPTION_BACKUP_RESTORE,
                access_rights, None, ctypes.byref(handle),
                ctypes.byref(disposition))
            if result == 0 and disposition.value == _REG_CREATED_NEW_KEY:
                # Never expected for the hives this is used on, and a created
                # key would be an empty one - saving it would write a
                # confidently empty hive rather than fail.
                ctypes.windll.advapi32.RegCloseKey(handle)
                raise OSError('The key did not exist and was created instead of opened: {}'.format(KeyPath))
        if result != 0:
            raise OSError('The RegOpenKeyExW() routine failed to open a key')
        self._src_handle = handle

    def _load_application_hive(self, HivePath):
        if not _APP_HIVES_SUPPORTED:
            raise OSError('Application hives are not supported on this system')
        handle = ctypes.c_void_p()
        result = ctypes.windll.advapi32.RegLoadAppKeyW(HivePath, ctypes.byref(handle), _KEY_READ, 0, 0)
        if result != 0:
            raise OSError('The RegLoadAppKeyW() routine failed to load a hive')
        self._src_handle = handle

    def _close_root_key(self):
        ctypes.windll.advapi32.RegCloseKey(self._src_handle)
        self._src_handle = None

    def _do_container_check(self, file_object):
        signature = file_object.read(4)
        if signature != b'regf':
            raise OSError('The exported hive is invalid')
        seq_1 = file_object.read(4)
        seq_2 = file_object.read(4)
        if seq_1 == seq_2 == b'\x01\x00\x00\x00':
            print('It seems that you run this script from inside of a container (see the docstring for the RegistryHivesLive class)', file=sys.stderr)
        file_object.seek(0, 0)

    def open_hive_by_key(self, RegistryPath, FilePath=None):
        if self._src_handle is not None:
            self._close_root_key()
        if self._dst_handle is not None:
            self._dst_handle = None
        PredefinedKey, KeyPath = self._resolve_path(RegistryPath)
        FilePath = self._create_destination_handle(FilePath)
        try:
            self._open_root_key(PredefinedKey, KeyPath)
        except Exception:
            self._close_destination_handle()
            raise
        result = ctypes.windll.ntdll.NtSaveKeyEx(self._src_handle, self._dst_handle, _REG_NO_COMPRESSION)
        if result == _STATUS_INVALID_PARAMETER:
            self._close_root_key()
            try:
                self._open_root_key(PredefinedKey, KeyPath, True)
            except Exception:
                self._close_destination_handle()
                raise
            result = ctypes.windll.ntdll.NtSaveKeyEx(self._src_handle, self._dst_handle, _REG_NO_COMPRESSION)
        if result != 0:
            self._close_root_key()
            self._close_destination_handle()
            raise OSError('The NtSaveKeyEx() routine failed with this status: {}'.format(hex(result)))
        self._close_root_key()
        f = NTFileLikeObject(self._dst_handle)
        self._do_container_check(f)
        return f

    def open_apphive_by_file(self, AppHivePath, FilePath=None):
        if self._src_handle is not None:
            self._close_root_key()
        if self._dst_handle is not None:
            self._dst_handle = None
        FilePath = self._create_destination_handle(FilePath)
        try:
            self._load_application_hive(AppHivePath)
        except Exception:
            self._close_destination_handle()
            raise
        result = ctypes.windll.ntdll.NtSaveKeyEx(self._src_handle, self._dst_handle, _REG_NO_COMPRESSION)
        if result != 0:
            self._close_root_key()
            self._close_destination_handle()
            raise OSError('The NtSaveKeyEx() routine failed with this status: {}'.format(hex(result)))
        self._close_root_key()
        f = NTFileLikeObject(self._dst_handle)
        self._do_container_check(f)
        return f

    def _resolve_predefined_key(self, PredefinedKeyStr):
        predef_str = PredefinedKeyStr.upper()
        if predef_str == 'HKU' or predef_str == 'HKEY_USERS':
            return _HKEY_USERS
        if predef_str == 'HKCU' or predef_str == 'HKEY_CURRENT_USER':
            if self._hkcu_handle is None:
                handle = ctypes.c_void_p()
                result = ctypes.windll.advapi32.RegOpenCurrentUser(_KEY_READ, ctypes.byref(handle))
                if result != 0:
                    raise OSError('The RegOpenCurrentUser() routine failed to open a root key')
                self._hkcu_handle = handle
            return self._hkcu_handle
        if predef_str == 'HKLM' or predef_str == 'HKEY_LOCAL_MACHINE':
            return _HKEY_LOCAL_MACHINE
        raise ValueError('Cannot resolve this predefined key or it is not supported: {}'.format(PredefinedKeyStr))

    def _resolve_path(self, PathStr):
        path_components = PathStr.split('\\')
        if len(path_components) == 0:
            raise ValueError('The registry path specified contains no path components')
        predefined_key = self._resolve_predefined_key(path_components[0])
        key_path = '\\'.join(path_components[1:])
        return (predefined_key, key_path)

    def _temp_file(self):
        buffer = ctypes.create_string_buffer(513)
        result = ctypes.windll.kernel32.GetTempFileNameA(b'.', b'hiv', 0, ctypes.byref(buffer))
        if result == 0:
            raise OSError('The GetTempFileNameA() routine failed to create a temporary file')
        tempfile = buffer.value.decode()
        return tempfile

# Class to parse Amcache.hve and store in a normalized SQLite database
def _carved_text(data):
    """A carved value as text, or a short hex preview when it is not text.

    A deleted value's bytes may be partly overwritten, so this never
    insists on a clean decode - it shows what is there.
    """
    if data is None:
        return None
    if isinstance(data, str):
        return data
    WHITESPACE = (chr(9), chr(10), chr(13))
    try:
        text = bytes(data).decode("utf-16le", "ignore").rstrip(chr(0))
        if text and all(ch.isprintable() or ch in WHITESPACE for ch in text):
            return text
    except Exception:
        pass
    try:
        return bytes(data)[:64].hex(" ")
    except Exception:
        return None

def quote(identifier):
    """Quote a SQL identifier. Amcache value names collide with SQL
    keywords - `exists`, `value`, `class`, `date`, `state` - and they are
    the hive's names, not ours to rename."""
    return '"%s"' % identifier.replace('"', '""')


class AmcacheParser:
    def __init__(self, file_path: str, normalized_db_path: str, windows_partition: str = "C:", offline_mode: bool = False, verify_hashes: bool = False):
        # One sqlite connection for the whole parse; see _connection().
        self._conn = None
        # Off unless asked for: it reads and hashes files from disk. Never
        # available offline - there is no filesystem to compare against.
        self.verify_hashes = bool(verify_hashes) and not offline_mode
        self._hashes_checked = 0
        self._hashes_mismatched = 0
        print("Loading Amcache.hve file...")
        sys.stdout.flush()  # Allow UI to process events
        
        # For offline mode, use python-registry directly (no admin privileges needed)
        # For live mode, use RegistryHivesLive (requires admin privileges)
        # Kept so the carve pass can get at the hive as a FILE; the live
        # path holds an open handle, which the allocator walk cannot read.
        self.hive_source = file_path
        if offline_mode:
            self.handle = file_path  # python-registry can open file path directly
            self.offline_mode = True
        else:
            self.handle = RegistryHivesLive().open_apphive_by_file(file_path)
            self.offline_mode = False
        
        sys.stdout.flush()  # Allow UI to process events
        self.normalized_db_path = normalized_db_path
        self.windows_partition = windows_partition  # Store Windows partition for path construction
        self._init_database()
        print("Database initialized.")
        sys.stdout.flush()  # Allow UI to process events

    def _init_database(self):
        """Create normalized database tables based on AMCACHE_SCHEMAS if they don't exist."""
        with sqlite3.connect(self.normalized_db_path) as conn:
            cursor = conn.cursor()
            for table_name, fields in AMCACHE_SCHEMAS.items():
                field_defs = ["id TEXT"]  # id not PRIMARY KEY to allow duplicates
                for field in fields:
                    # Quoted, always. Amcache value names include `exists`,
                    # `value`, `class`, `date`, `source`, `state` and others
                    # that are SQL keywords - and the hand-maintained list of
                    # keywords this used to carry did not include `exists`, so
                    # the table simply failed to create. Quoting removes the
                    # need to keep such a list correct.
                    field_defs.append('"%s" TEXT' % field)
                create_table_sql = f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    {', '.join(field_defs)}
                )
                """
                cursor.execute(create_table_sql)

                # CREATE TABLE IF NOT EXISTS does nothing to a table that is
                # already there, so a case parsed before this schema kept its
                # old columns and every insert failed on the new ones - 130
                # columns missing on a real case database.
                #
                # Added, never rebuilt. Dropping and recreating would take the
                # columns and discard the rows with them, and an AmCache entry
                # that has since aged out of the hive exists nowhere else.
                # Older rows simply read NULL in the new columns.
                # Compared case-insensitively, because SQLite is: an older
                # case carries `Audio_Render_Driver` where the schema now says
                # `audio_render_driver`, and a case-sensitive check tries to
                # add a column SQLite already considers present.
                cursor.execute("PRAGMA table_info(%s)" % quote(table_name))
                existing = {c[1].lower() for c in cursor.fetchall()}
                for field in fields:
                    if field.lower() not in existing:
                        cursor.execute("ALTER TABLE %s ADD COLUMN %s TEXT"
                                       % (quote(table_name), quote(field)))

                # Add index on id for fast duplicate checking
                cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_id ON {table_name} (id)")
                # Yield to UI periodically during database initialization
                sys.stdout.flush()
            conn.commit()

    def _connection(self):
        """One connection for the whole parse.

        _check_entry_exists and _normalize_and_insert each used to open and
        close their own sqlite3 connection, so a hive with ~7,000 entries
        performed ~14,000 separate file opens before any of the work counted.
        It was correct and invisible - the rows were right, and the only
        symptom was the parse taking far longer than the work in it.
        """
        if self._conn is None:
            self._conn = sqlite3.connect(self.normalized_db_path)
        return self._conn

    def _close_connection(self):
        if self._conn is not None:
            self._conn.commit()
            self._conn.close()
            self._conn = None

    @staticmethod
    def _match_key(field: str, data_json: Dict[str, Any]):
        """Find the registry value a column came from.

        The column names in AMCACHE_SCHEMAS are snake_case forms of real value
        names, but no single CamelCase rule reproduces all of them -
        `TotalUserConnectableTypeCPorts` and `Accelerometer3D` both defeat the
        obvious one. So the exact forms are tried first and then both sides are
        normalised by dropping underscores and case, which matches every value
        name observed in a real hive with no collisions.

        Returns the value, or None when the entry simply does not carry it.
        """
        if field == "default_value" and "(default)" in data_json:
            return data_json["(default)"]

        candidates = [
            field,
            ''.join(w.capitalize() if i else w
                    for i, w in enumerate(field.split('_'))),
            ''.join(w.capitalize() for w in field.split('_')),
            field.upper(),
            field.lower(),
        ]
        for c in candidates:
            if c in data_json:
                return data_json[c]

        target = field.replace('_', '').lower()
        for name, value in data_json.items():
            if name.replace('_', '').lower() == target:
                return value
        return None

    def _check_entry_exists(self, table_name: str, entry_id: str,
                            data_json: Dict[str, Any]) -> bool:
        """True if an identical entry is already stored (parsed_at ignored)."""
        cursor = self._connection().cursor()
        if table_name == "UnknownSubkeys":
            cursor.execute("SELECT data FROM %s WHERE id = ?" % table_name,
                           (entry_id,))
            new_data = json.dumps(
                {k: v for k, v in data_json.items() if k != "parsed_at"},
                sort_keys=True)
            return any(row[0] == new_data for row in cursor.fetchall())

        if table_name in NAME_VALUE_TABLES:
            # Identity here is the (entry, name) pair, not the whole row.
            return False

        cursor.execute("PRAGMA table_info(%s)" % table_name)
        table_columns = [c[1] for c in cursor.fetchall()]
        cursor.execute("SELECT * FROM %s WHERE id = ?" % table_name, (entry_id,))
        rows = cursor.fetchall()
        new_data = {k: str(v) for k, v in data_json.items()
                    if k not in ("id", "parsed_at")}
        for row in rows:
            existing = {table_columns[i]: (str(v) if v is not None else None)
                        for i, v in enumerate(row) if i < len(table_columns)}
            if all(new_data.get(k) == existing.get(k) for k in new_data):
                return True
        return False

    def _normalize_and_insert(self, table_name: str, entry_id: str,
                              data_json: Dict[str, Any],
                              key_last_write: str = None):
        """Store one AmCache entry.

        Every column in AMCACHE_SCHEMAS is a value name observed in a real
        hive, so the generic mapping below is all that is needed. The
        per-table special cases that used to sit here are gone, and with them
        the values they invented: `Mare` was given a name built from its entry
        id, a hardcoded type and state, and a FABRICATED path under Program
        Files - 0 of 200 of those paths existed on disk. The real path is in
        the entry's own `restore` value, which is now stored as it is found.
        A column with no value in the hive is left NULL.
        """
        if table_name not in AMCACHE_SCHEMAS:
            return
        parsed_at = get_current_forensic_timestamp()

        if table_name in NAME_VALUE_TABLES:
            self._insert_name_value(table_name, entry_id, data_json,
                                    key_last_write, parsed_at)
            return

        if table_name == "UnknownSubkeys":
            subkey_name = data_json.get("subkey_name", "")
            payload = {k: v for k, v in data_json.items() if k != "subkey_name"}
            if self._check_entry_exists(table_name, entry_id, data_json):
                return
            cursor = self._connection().cursor()
            cursor.execute(
                "INSERT INTO UnknownSubkeys "
                "(id, subkey_name, data, key_last_write, parsed_at) "
                "VALUES (?, ?, ?, ?, ?)",
                [entry_id, subkey_name,
                 json.dumps({k: v for k, v in data_json.items()
                             if k != "parsed_at"}, sort_keys=True),
                 key_last_write, parsed_at])
            return

        if self._check_entry_exists(table_name, entry_id, data_json):
            return

        fields = AMCACHE_SCHEMAS[table_name]
        values = {"id": entry_id}
        for field in fields:
            if field == "parsed_at":
                values[field] = parsed_at
            elif field == "key_last_write":
                values[field] = key_last_write
            else:
                v = self._match_key(field, data_json)
                values[field] = str(v) if v is not None else None

        # ---- normalised timestamps, beside the raw string, never over it
        for col in AMCACHE_DATE_COLUMNS.get(table_name, ()):
            when = _parse_amcache_date(values.get(col))
            values[col + "_utc"] = (format_forensic_timestamp(when)
                                    if when else None)
        for col in AMCACHE_EPOCH_COLUMNS.get(table_name, ()):
            when = _parse_amcache_epoch(values.get(col))
            values[col + "_utc"] = (format_forensic_timestamp(when)
                                    if when else None)

        # ---- is this FileId a partial hash?
        #
        # AmCache hashes only the first 30 MiB of a file, so a larger binary's
        # FileId can never match a published SHA-1. It is the only hash
        # Crow-Eye matches IOCs against, and without this an analyst reads a
        # non-match as "not this file". Decided from the cached Size, so it
        # works against an image with no filesystem; a row with no Size stays
        # NULL rather than being guessed at.
        if table_name == "InventoryApplicationFile":
            size = values.get("size")
            try:
                size = int(str(size).strip()) if size not in (None, "") else None
            except ValueError:
                size = None
            if size is not None:
                values["file_id_is_partial"] = "1" if size > AMCACHE_HASH_LIMIT else "0"
            if self.verify_hashes and values.get("file_id"):
                values["file_id_verified"] = self._verify_file_id(
                    values.get("lower_case_long_path"), values["file_id"])

        # Mare's `restore` is a delimited blob - "RootDirPath|C:\...;
        # AddPlaceholderCustom|..." - and the directory inside it is the real
        # one. This is a DECODE of a field that is present, not a guess: the
        # column stays NULL when `restore` carries no RootDirPath. It replaces
        # a fabricated path, and the difference is measurable - 245 of 362 of
        # these exist on disk, against 0 of 200 of the invented ones.
        if table_name == "Mare" and values.get("restore"):
            for part in str(values["restore"]).split(";"):
                if part.startswith("RootDirPath|"):
                    values["root_dir_path"] = part.split("|", 1)[1]
                    break

        present = [f for f in fields if values.get(f) is not None]
        cursor = self._connection().cursor()
        cursor.execute(
            "INSERT INTO %s (%s) VALUES (%s)"
            % (quote(table_name),
               ", ".join(quote(c) for c in ["id"] + present),
               ", ".join(["?"] * (1 + len(present)))),
            [entry_id] + [values[f] for f in present])

    # The pre-Windows-10 layout: Root\File\{VolumeGUID}\{FileReference} with
    # NUMBERED value names, and Root\Programs. Two levels below Root, where the
    # modern schema is one, so the walk above reaches none of it.
    #
    # It is detected and REPORTED, not decoded. The numbered map is well
    # documented - 15 is the path, 101 the SHA-1, 100 the ProgramId, 6 the
    # size, f the compile time, 11/12/17 FILETIMEs - but no Windows 7 or 8 hive
    # was available to test a decoder against, and untested decoding of
    # evidence is worse than an honest refusal. Silence would be worst of all:
    # before this, such a hive produced no file entries and said nothing.
    LEGACY_SUBKEYS = ("File", "Programs")

    def check_for_legacy_schema(self, root):
        """Say so if this hive carries the Windows 7/8 layout.

        Returns the legacy subkey names found. A hive carrying BOTH layouts
        parses its Inventory* side as normal and still reports the legacy side
        as unread, so a mixed hive is never silently half-parsed.
        """
        try:
            names = [k.name() for k in root.subkeys()]
        except Exception:
            return []

        legacy = [n for n in names if n in self.LEGACY_SUBKEYS]
        if not legacy:
            return []

        modern = [n for n in names if n.startswith("Inventory")]
        entries = 0
        for name in legacy:
            try:
                for volume in root.subkey(name).subkeys():
                    entries += len(list(volume.subkeys())) or 1
            except Exception:
                pass

        print("[FAIL] This hive carries the Windows 7/8 AmCache schema "
              "(Root\\%s) with about %d entry key(s) below it. "
              "That layout is NOT parsed by this build, so those entries are "
              "not in the output."
              % (", Root\\".join(legacy), entries))
        if modern:
            print("[NOTE] The hive also carries %d modern Inventory* key(s), "
                  "which ARE parsed below. This hive is only partly read."
                  % len(modern))
        else:
            print("[NOTE] No Inventory* keys are present, so this parse will "
                  "produce no file entries at all.")
        return legacy

    def classify_program_association(self):
        """Mark each file entry as associated with an installed program, or not.

        The standard split. A file whose ProgramId resolves to an
        InventoryApplication row belongs to something installed; one that
        does not was seen on disk belonging to no installed program, and
        that is where dropped and portable binaries show up.

        Done in one pass AFTER both tables are written, because the file
        entries are parsed before the programs - it cannot be decided row
        by row during the walk.
        """
        try:
            cursor = self._connection().cursor()
            cursor.execute(
                "UPDATE InventoryApplicationFile SET program_association = "
                "CASE WHEN program_id IS NULL OR program_id = %s THEN NULL "
                "     WHEN EXISTS (SELECT 1 FROM InventoryApplication a "
                "                  WHERE a.program_id = "
                "                        InventoryApplicationFile.program_id) "
                "     THEN %s ELSE %s END" % ("''", "'associated'",
                                             "'unassociated'"))
            self._connection().commit()
        except Exception as exc:                   # pragma: no cover
            print("[Amcache] Could not classify program association: %s" % exc)

    def carve_deleted_entries(self, hive_path=None):
        """Recover AmCache entries that were deleted from the hive.

        Deleting a registry key does not erase it. Windows flips the cell's
        size field positive, marks it free, and moves on - the signature, the
        name, the timestamp and the values are all still there until something
        allocates over that space. A key unlinked from the tree is invisible to
        every tree walker, including the one above, and is still in the file.

        This does not implement a second carver. It points the one Crow-Eye
        already has - registry_hive_walk.walk_hive - at Amcache.hve, and stores
        what comes back in the same shape Regclaw uses for
        registry_carved_keys / registry_carved_values, so the two artifacts
        read alike.

        No reference AmCache parser recovers deleted entries at all.

        A live export cannot pay off and the result says so: NtSaveKeyEx
        serialises the hive as the kernel holds it, which is a REORGANISED
        hive with no free space. Measured on this machine: 1,777 bins, no
        error, and zero carved cells. It is still run, so that zero is a
        measurement rather than an assumption, and the reorganisation flag is
        reported alongside it.

        Never fatal. walk_hive returns an `error` rather than raising, and a
        parse that cannot carve must still parse.
        """
        temp_dir = None
        try:
            if hive_path is None:
                hive_path, temp_dir = self._hive_as_file()
            if not hive_path:
                print("[Amcache] Carving skipped: no hive file to walk")
                return

            walk = registry_hive_walk.walk_hive(hive_path)
            if walk.error:
                print("[Amcache] Carving skipped: %s" % walk.error)
                return

            reorganized = getattr(walk, "reorganized_raw", None)
            print("[Amcache] Free-space walk: %d bins, %d free cell(s), "
                  "%d byte(s) free%s"
                  % (walk.bins, walk.cells_free, walk.free_bytes,
                     "; hive was REORGANISED, so deleted records were "
                     "discarded before this copy was made" if reorganized
                     else ""))

            parsed_at = get_current_forensic_timestamp()
            cursor = self._connection().cursor()
            keys = values = 0
            for record in walk.carved_keys:
                when = ""
                if record.get("timestamp_raw"):
                    try:
                        when = format_forensic_timestamp(
                            filetime_to_datetime(record["timestamp_raw"]))
                    except Exception:
                        when = ""
                cursor.execute(
                    "INSERT OR IGNORE INTO AmcacheCarvedKeys "
                    "(id, cell_offset, key_name, key_path, parent_resolved, "
                    "key_last_write, subkey_count, value_count, record_state, "
                    "parsed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (str(record["cell_offset"]), record["cell_offset"],
                     record.get("key_name", ""), record.get("key_path", ""),
                     1 if record.get("parent_resolved") else 0, when,
                     record.get("subkey_count"), record.get("value_count"),
                     "deleted", parsed_at))
                keys += 1
                for value in record.get("values", []):
                    cursor.execute(
                        "INSERT OR IGNORE INTO AmcacheCarvedValues "
                        "(id, cell_offset, parent_cell_offset, key_path, "
                        "value_name, value_type, data_size, is_inline, data, "
                        "record_state, parsed_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (str(value["cell_offset"]), value["cell_offset"],
                         record["cell_offset"], record.get("key_path", ""),
                         value.get("value_name", ""),
                         str(value.get("value_type", "")),
                         value.get("data_size"),
                         1 if value.get("inline") else 0,
                         _carved_text(value.get("data")),
                         "deleted", parsed_at))
                    values += 1
            self._connection().commit()
            print("[Amcache] Recovered %d deleted key(s) and %d deleted "
                  "value(s) from free space" % (keys, values))
        except Exception as exc:                       # pragma: no cover
            print("[Amcache] Carving failed, parse continues: %s" % exc)
        finally:
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _hive_as_file(self):
        """A path to the hive, exporting it first if we only hold a handle.

        The allocator walk reads the FILE; the live path holds an open
        NtSaveKeyEx handle instead. RegistryHivesLive already knows how to
        write the export to a path, so this asks it for one and cleans up
        afterwards - the same tempfile.mkdtemp / shutil.rmtree shape
        user_identity.live_hive_export uses for SAM and SECURITY.
        """
        if isinstance(self.hive_source, (str, bytes, os.PathLike)) \
                and os.path.exists(self.hive_source):
            return self.hive_source, None
        if self.offline_mode:
            return None, None
        temp_dir = tempfile.mkdtemp(prefix="amcache_carve_")
        out = os.path.join(temp_dir, "Amcache.hve")
        try:
            RegistryHivesLive().open_apphive_by_file(self.hive_source, out)
        except Exception as exc:
            print("[Amcache] Could not export the hive for carving: %s" % exc)
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None, None
        return out, temp_dir

    def _verify_file_id(self, path, file_id):
        """Does the cached FileId still match the file on disk?

        Returns "match", "mismatch", or None when there is nothing to compare -
        no path, the file is gone, or it cannot be read.

        A mismatch is a finding, not noise: the binary was replaced after
        AmCache recorded it, and the hash in the hive describes what used to be
        there. On this machine 12 of 446 readable files came back mismatched.

        Bounded on purpose. It reads at most the first 30 MiB, which is all
        AmCache hashes anyway, and it only runs when the operator asked for it
        (`verify_hashes`). Hashing thousands of files is not something a parse
        should do because somebody forgot to turn it off, and an offline parse
        has no filesystem to compare against at all.
        """
        if not path or "\t" in str(path):
            return None
        try:
            if not os.path.isfile(path):
                return None
            digest = hashlib.sha1()
            read = 0
            with open(path, "rb") as handle:
                while read < AMCACHE_HASH_LIMIT:
                    chunk = handle.read(min(1 << 20, AMCACHE_HASH_LIMIT - read))
                    if not chunk:
                        break
                    digest.update(chunk)
                    read += len(chunk)
        except (OSError, PermissionError):
            return None

        self._hashes_checked += 1
        # The stored form is four zeros then the hash; compare the hash only.
        expected = str(file_id)[4:].lower()
        if digest.hexdigest() == expected:
            return "match"
        self._hashes_mismatched += 1
        return "mismatch"

    def _insert_name_value(self, table_name, entry_id, data_json,
                           key_last_write, parsed_at):
        """One row per registry value, for the wide and the unverifiable subkeys.

        DeviceCensus used to be a single JSON blob in one column, which no SQL
        query could reach into - 237 distinct value names on the reference
        system, including the machine's AAD device id and activation channel.
        """
        cursor = self._connection().cursor()
        for name, value in data_json.items():
            if name == "parsed_at":
                continue
            cursor.execute(
                "SELECT 1 FROM %s WHERE id = ? AND name = ? AND value IS ? "
                "LIMIT 1" % table_name,
                (entry_id, name, str(value) if value is not None else None))
            if cursor.fetchone():
                continue
            cursor.execute(
                "INSERT INTO %s (id, entry, name, value, key_last_write, "
                "parsed_at) VALUES (?, ?, ?, ?, ?, ?)" % table_name,
                [entry_id, entry_id, name,
                 str(value) if value is not None else None,
                 key_last_write, parsed_at])

    def display_normalized_data(self):
        """Display normalized database contents in a tabular format."""
        print("[Amcache] Displaying normalized data...")
        with sqlite3.connect(self.normalized_db_path) as conn:
            cursor = conn.cursor()
            tables = [table for table in AMCACHE_SCHEMAS.keys()]
            print("\n[Amcache] === NORMALIZED DATABASE TABLES ===\n")
            
            # Process tables in batches to prevent UI freezing
            batch_size = 3  # Process 3 tables at a time
            total_tables = len(tables)
            
            if TQDM_AVAILABLE:
                progress_bar = tqdm(total=total_tables, desc="[Amcache] Processing tables", unit="table")
                
                for i in range(0, total_tables, batch_size):
                    batch = tables[i:i+batch_size]
                    for table in batch:
                        cursor.execute(f"SELECT COUNT(*) FROM {table}")
                        count = cursor.fetchone()[0]
                        if count > 0:
                            print(f"\n[Amcache] === {table} ({count} entries) ===\n")
                            fields = ["id"] + [f for f in AMCACHE_SCHEMAS[table] if f != "parsed_at"][:4] + ["parsed_at"]
                            cursor.execute(f"SELECT {', '.join(fields)} FROM {table} LIMIT 10")
                        progress_bar.update(1)
                    # Allow UI to process events between batches
                    sys.stdout.flush()
                progress_bar.close()
            else:
                print(f"[Amcache] Processing {total_tables} tables...")
                for i in range(0, total_tables, batch_size):
                    batch = tables[i:i+batch_size]
                    for j, table in enumerate(batch):
                        current = i + j
                        percent = int((current / total_tables) * 100) if total_tables > 0 else 0
                        print(f"[Amcache] Processing table {current+1}/{total_tables} ({percent}%)")
                        
                        cursor.execute(f"SELECT COUNT(*) FROM {table}")
                        count = cursor.fetchone()[0]
                        if count > 0:
                            print(f"\n[Amcache] === {table} ({count} entries) ===\n")
                            fields = ["id"] + [f for f in AMCACHE_SCHEMAS[table] if f != "parsed_at"][:4] + ["parsed_at"]
                            cursor.execute(f"SELECT {', '.join(fields)} FROM {table} LIMIT 10")
                    # Allow UI to process events between batches
                    sys.stdout.flush()
                    rows = cursor.fetchall()
                    header = "\t".join(fields)
                    print(header)
                    print("-" * len(header))
                    for row in rows:
                        print("\t".join(str(cell) if cell is not None else "None" for cell in row))
                    if count > 10:
                        print(f"... and {count - 10} more entries")
            if not tables:
                print("No normalized data available.")
        print("Display complete.")

    def parse(self, search_key: str | list = None):
        """Parse Amcache.hve and process specified subkeys with a progress indicator."""
        # Amcache.hve is a hive like any other: Windows keeps it open and its
        # outstanding changes sit in Amcache.hve.LOG1/.LOG2 beside it. Reading
        # the raw FILE reports whatever happened to be flushed, so the offline
        # path replays the logs first.
        #
        # Only the offline path. In live mode `self.handle` is an already-open
        # NT file object from NtSaveKeyEx, not a path - and hive_for_reading
        # calls os.path.abspath on what it is given, so passing the handle
        # raised TypeError and the live parse produced nothing at all. There
        # is nothing to replay there anyway: NtSaveKeyEx snapshots the hive as
        # the kernel currently holds it, which already includes everything the
        # logs would have applied.
        if isinstance(self.handle, (str, bytes, os.PathLike)):
            self.handle = registry_transaction_log.hive_for_reading(self.handle)
        r = Registry.Registry(self.handle)
        # Yield to UI before opening root
        sys.stdout.flush()
        root = r.open("Root")
        # Yield to UI after opening root
        sys.stdout.flush()
        self.check_for_legacy_schema(root)
        root_subkeys = root.subkeys()
        # Yield to UI after loading registry
        sys.stdout.flush()
        if search_key is not None and isinstance(search_key, str) and search_key not in [subkey.name() for subkey in root_subkeys]:
            print(f"The key '{search_key}' does not exist")
            sys.exit(1)
        elif search_key is not None and isinstance(search_key, list):
            for key in search_key:
                if key not in [subkey.name() for subkey in root_subkeys]:
                    print(f"The key '{key}' does not exist")
                    sys.exit(1)
        print("Processing subkeys...")
        
        # Filter relevant subkeys first
        relevant_subkeys = []
        for subkey in root_subkeys:
            if search_key is not None and isinstance(search_key, str) and subkey.name() != search_key:
                continue
            elif search_key is not None and isinstance(search_key, list) and subkey.name() not in search_key:
                continue
            relevant_subkeys.append(subkey)
            
        # Process subkeys in batches to prevent UI freezing
        total = len(relevant_subkeys)
        batch_size = max(1, min(10, total // 20))  # Adjust batch size based on total count
        print(f"[Amcache] Processing {total} subkeys in batches of {batch_size}...")
        
        if TQDM_AVAILABLE:
            progress_bar = tqdm(total=total, desc="[Amcache] Parsing subkeys", unit="subkey")
            
            for i in range(0, total, batch_size):
                batch = relevant_subkeys[i:i+batch_size]
                for j, subkey in enumerate(batch):
                    subkey_name = subkey.name()
                    normalized_subkey_name = subkey_name
                    if subkey_name == "InventoryMiscellaneousUUPInfo":
                        normalized_subkey_name = "InventoryMiscellaneousUupInfo"
                    # Yield to UI periodically during processing
                    if j % 5 == 0:  # Every 5 subkeys
                        sys.stdout.flush()
                    list(map(lambda k: self.mapper(k, normalized_subkey_name), subkey.subkeys()))
                    progress_bar.update(1)
                # Yield to UI after processing each batch
                sys.stdout.flush()
            progress_bar.close()
        else:
            for i in range(0, total, batch_size):
                batch = relevant_subkeys[i:i+batch_size]
                for j, subkey in enumerate(batch):
                    current = i + j
                    # Calculate percentage and create a progress bar
                    percent = int((current / total) * 100) if total > 0 else 0
                    bar_length = 20
                    filled_length = int(bar_length * current // total) if total > 0 else 0
                    bar = '#' * filled_length + '.' * (bar_length - filled_length)
                    
                    # Print progress
                    sys.stdout.write(f"\r[{bar}] {percent}% ({current+1}/{total} subkeys)")
                    sys.stdout.flush()
                    
                    subkey_name = subkey.name()
                    normalized_subkey_name = subkey_name
                    if subkey_name == "InventoryMiscellaneousUUPInfo":
                        normalized_subkey_name = "InventoryMiscellaneousUupInfo"
                    list(map(lambda k: self.mapper(k, normalized_subkey_name), subkey.subkeys()))
                # Allow UI to process events between batches
                sys.stdout.flush()
            print()  # Newline after progress bar
        self.classify_program_association()
        self.carve_deleted_entries()
        self._close_connection()
        if self.verify_hashes:
            print("[Amcache] FileId re-hashed against disk on %d file(s); "
                  "%d no longer match what AmCache recorded"
                  % (self._hashes_checked, self._hashes_mismatched))
        print("\n[Amcache] Processing complete.")

    def mapper(self, key: Registry.RegistryKey, subkey_name: str) -> None:
        """Map registry key values to normalized database entries."""
        key_name = key.name()
        # The KEY's own LastWriteTime - when Windows last wrote this entry.
        # When the Compatibility Appraiser wrote the entry - not when
        # anything ran. It was being dropped on the floor, and `parsed_at` is
        # when Crow-Eye ran and belongs on no timeline. Batch-written, so it
        # orders InventoryApplicationFile usefully and the driver, device and
        # Mare tables barely at all. Formatted through the shared helper so it
        # matches every other timestamp in the product.
        try:
            key_last_write = format_forensic_timestamp(key.timestamp())
        except Exception:
            key_last_write = None
        values_dict = {}
        # Process values in smaller chunks to prevent UI freezing
        values = key.values()
        if len(values) > 20:  # Only flush for keys with many values
            sys.stdout.flush()
            
        for value in values:
            values_dict[value.name()] = str(value.value())
            
        # Yield to UI before database operations
        if len(values_dict) > 50:  # Only flush for large dictionaries
            sys.stdout.flush()
            
        if subkey_name in AMCACHE_SCHEMAS:
            self._normalize_and_insert(subkey_name, key_name, values_dict,
                                       key_last_write)
        else:
            # Store unrecognized subkey data in UnknownSubkeys table
            values_dict["subkey_name"] = subkey_name
            self._normalize_and_insert("UnknownSubkeys", key_name, values_dict,
                                       key_last_write)

def isAdmin() -> bool:
    """Check if the script is running with administrative privileges."""
    try:
        return os.getuid() == 0
    except AttributeError:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0

def parse_amcache_hive(case_path=None, offline_mode=False, db_path=None, windows_partition="C:"):
    """Parse Amcache hive file and save data to SQLite database.
    
    Args:
        case_path (str, optional): Path to the case directory. Defaults to None.
        offline_mode (bool, optional): Whether to run in offline mode. Defaults to False.
        db_path (str, optional): Path to save the database file. Defaults to None.
        windows_partition (str, optional): Windows partition letter (e.g., "C:", "D:"). Defaults to "C:".
    
    Returns:
        str: Path to the Amcache database file
    """
    print(f"[Amcache] Starting Amcache parser (Windows partition: {windows_partition})...")
    print("[Amcache] This may take a few minutes depending on the size of the Amcache hive.")
    sys.stdout.flush()
    
    # Function to allow UI to process events during long operations
    def yield_to_ui():
        """Yield control to UI thread to prevent freezing"""
        # This small delay allows the UI to process events
        if hasattr(sys, 'stdout') and hasattr(sys.stdout, 'flush'):
            sys.stdout.flush()
    
    # Set database path based on case management
    if not db_path:
        if case_path and os.path.exists(case_path):
            # Case mode - save to Target_Artifacts in case directory
            artifacts_dir = os.path.join(case_path, "Target_Artifacts")
            os.makedirs(artifacts_dir, exist_ok=True)
            db_path = os.path.join(artifacts_dir, "amcache.db")
        else:
            # No case - save to current directory
            db_path = "amcache.db"
    
    # Select Amcache.hve file path
    if offline_mode:
        # Offline mode - use provided path
        if case_path and os.path.exists(case_path):
            filepath = os.path.join(case_path, "Amcache.hve")
            
            # Case-insensitive check for Linux
            if not os.path.exists(filepath):
                for f in os.listdir(case_path):
                    if f.lower() == "amcache.hve":
                        filepath = os.path.join(case_path, f)
                        break
        else:
            filepath = OFFLINE_AMCACHE_PATH
    else:
        # Live mode - use dynamic path based on Windows partition
        if system() == 'Windows' and int(version().split(".")[0]) < 7:
            print("[Amcache Error] Your system is not compatible with Amcache.hve")
            return None
        filepath = get_live_amcache_path(windows_partition)

    if not os.path.exists(filepath):
        print(f"[Amcache Error] Input file does not exist: {filepath}")
        return None

    try:
        ap = AmcacheParser(filepath, db_path, windows_partition)
        yield_to_ui()  # Allow UI to process events before starting parse
        ap.parse(search_key=SEARCH_KEYS)
        print(f"[Amcache] Data saved to {db_path}")
        return db_path
    except OSError as e:
        if isAdmin():
            print(f"[Amcache Error] Error loading hive: {str(e)}")
        else:
            print("[Amcache Error] Error loading hive. Try execute as administrator")
        return None

def amcache_parser(case_path=None, offline_mode=False, windows_partition="C:"):
    """Wrapper function for Amcache parser with case management integration.
    
    Args:
        case_path (str, optional): Path to the case directory. Defaults to None.
        offline_mode (bool, optional): Whether to run in offline mode. Defaults to False.
        windows_partition (str, optional): Windows partition letter (e.g., "C:", "D:"). Defaults to "C:".
    
    Returns:
        dict: Parser results including record counts and status
    """
    print(f"Starting Amcache parser (Windows partition: {windows_partition})...")
    
    # Set database path based on case management
    if case_path and os.path.exists(case_path):
        # Case mode - save to Target_Artifacts in case directory (flat structure)
        artifacts_dir = os.path.join(case_path, "Target_Artifacts")
        os.makedirs(artifacts_dir, exist_ok=True)
        db_path = os.path.join(artifacts_dir, "amcache.db")
    else:
        # No case - save to current directory
        db_path = "amcache.db"
    
    # Select Amcache.hve file path
    if offline_mode:
        # Offline mode - try multiple possible locations (input from live_acquisition)
        if case_path:
            possible_paths = [
                os.path.join(case_path, "live_acquisition", "amcache", "Amcache.hve"),
                os.path.join(case_path, "Amcache.hve"),
                os.path.join(case_path, "Target_Artifacts", "amcache", "Amcache.hve"),
                os.path.join(case_path, "Target_Artifacts", "Amcache.hve")
            ]
            
            filepath = None
            for path in possible_paths:
                if os.path.exists(path):
                    filepath = path
                    break
                else:
                    # Case-insensitive fallback for Linux
                    dirname = os.path.dirname(path)
                    basename = os.path.basename(path)
                    if os.path.exists(dirname):
                        for f in os.listdir(dirname):
                            if f.lower() == basename.lower():
                                filepath = os.path.join(dirname, f)
                                break
                    if filepath:
                        break
            
            if not filepath:
                filepath = possible_paths[0]  # Default to first option
        else:
            filepath = OFFLINE_AMCACHE_PATH
    else:
        # Live mode - use dynamic path based on Windows partition
        if system() == 'Windows' and int(version().split(".")[0]) < 7:
            print("Your system is not compatible with Amcache.hve")
            return {'success': False, 'records': 0, 'error': 'System not compatible with Amcache.hve'}
        filepath = get_live_amcache_path(windows_partition)

    if not os.path.exists(filepath):
        print(f"[Amcache] Input file does not exist: {filepath}")
        return {'success': False, 'records': 0, 'error': f'Input file does not exist: {filepath}', 'output_path': db_path}

    try:
        ap = AmcacheParser(filepath, db_path, windows_partition, offline_mode=offline_mode)
        ap.parse(search_key=SEARCH_KEYS)
        print(f"[Amcache] Data saved to {db_path}")
        
        # Count total records from database
        import sqlite3
        total_records = 0
        try:
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                # Get all table names
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = cursor.fetchall()
                # Count records in each table
                for table in tables:
                    cursor.execute(f"SELECT COUNT(*) FROM {table[0]}")
                    count = cursor.fetchone()[0]
                    total_records += count
        except Exception as e:
            print(f"[Amcache] Warning: Could not count records: {e}")
            total_records = 0
        
        return {'success': True, 'records': total_records, 'output_path': db_path}
    except OSError as e:
        error_msg = f"Error loading hive: {str(e)}"
        if isAdmin():
            print(f"[Amcache Error] {error_msg}")
        else:
            print("[Amcache Error] Error loading hive. Try execute as administrator")
            error_msg += " (Try running as administrator)"
        return {'success': False, 'records': 0, 'error': error_msg, 'output_path': db_path}

def main():
    """Main function to run the Amcache parser."""
    db_path = amcache_parser()
    if db_path:
        # Create parser and display data
        try:
            ap = AmcacheParser(LIVE_AMCACHE_PATH if LIVE_ANALYSIS else OFFLINE_AMCACHE_PATH, db_path)
            ap.display_normalized_data()
            print("Amcache parsing complete.")
        except Exception as e:
            print(f"Error displaying data: {str(e)}")

if __name__ == '__main__':
    main()