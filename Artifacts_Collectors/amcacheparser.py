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
import json
import re
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False

# Configuration variables
LIVE_ANALYSIS = True  # Set to True for live analysis, False for offline analysis
LIVE_AMCACHE_PATH = r"C:\Windows\AppCompat\Programs\Amcache.hve"  # Path for live Amcache.hve
OFFLINE_AMCACHE_PATH = r"E:\Crow Eye research\Amcache.hve"  # Path for offline Amcache.hve
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
NORMALIZED_DATABASE_PATH = os.path.join(SCRIPT_DIR, r"Amcashedb.db")  # Normalized database path
SEARCH_KEYS = None  # Set to None for all keys or a list like ["Root\\InventoryApplication"]

# Schema for normalized database tables (name after id if present, parsed_at last)
AMCACHE_SCHEMAS = {
    "InventoryApplication": [
        "name", "program_id", "program_instance_id", "version", "publisher", "language", "source",
        "root_dir_path", "store_app_type", "inbox_modern_app", "manifest_path", "package_full_name",
        "install_date", "bundle_manifest_path", "parsed_at"],
    "InventoryApplicationFile": [
        "name", "file_id", "lower_case_long_path", "original_file_name", "publisher",
        "version", "bin_file_version", "binary_type", "product_name", "product_version", "link_date",
        "bin_product_version", "size", "language", "usn", "parsed_at"],
    "InventoryApplicationShortcut": [
        "ShortcutPath", "ShortcutTargetPath", "ShortcutAumid", "ShortcutProgramId", "parsed_at"],
    "InventoryDriverBinary": [
        "driver_name", "inf", "driver_version", "product", "product_version", "wdf_version",
        "driver_company", "service", "driver_in_box", "driver_signed", "driver_is_kernel_mode",
        "driver_id", "driver_last_write_time", "driver_type", "driver_time_stamp", "driver_check_sum",
        "image_size", "parsed_at"],
    "InventoryDriverPackage": [
        "driver_package_strong_name", "provider", "driver_in_box", "inf_name", "hwids", "parsed_at"],
    "InventoryDeviceContainer": [
        "model_name", "icon", "friendly_name", "model_number", "manufacturer", "model_id",
        "primary_category", "categories", "is_machine_container", "discovery_method", "is_connected",
        "is_active", "is_paired", "is_networked", "state", "parsed_at"],
    "InventoryDevicePnp": [
        "service", "class", "class_guid", "model", "upper_filters", "lower_filters", "enumerator",
        "upper_class_filters", "lower_class_filters", "install_state", "device_state", "location_paths",
        "parsed_at"],
    "InventoryDeviceMediaClass": [
        "Audio_Render_Driver", "Audio_Capture_Driver", "parsed_at"],
    "InventoryDeviceInterface": ["parsed_at"],
    "InventoryDeviceUsbHubClass": [
        "device_capabilities", "device_speed", "parsed_at"],
    "InventoryMiscellaneous": [
        "misc_name", "misc_type", "misc_value", "misc_source", "parsed_at"],
    "InventoryMiscellaneousMemorySlotArrayInfo": [
        "memory_slot_array_id", "memory_slot_array_location", "memory_slot_array_use",
        "memory_slot_array_number_of_slots", "parsed_at"],
    "InventoryMiscellaneousUupInfo": [
        "uup_name", "uup_id", "uup_version", "uup_description", "uup_state", "uup_install_source",
        "uup_publisher", "parsed_at"],
    "InventoryMiscellaneousUser": [
        "user_name", "user_sid", "user_type", "parsed_at"],
    "Mare": [
        "mare_name", "mare_id", "mare_type", "mare_state", "mare_path", "mare_flags", "mare_data",
        "parsed_at"],
    "DeviceCensus": [
        "data", "parsed_at"  # Single column for JSON data plus timestamp
    ],
    "UnknownSubkeys": [
        "subkey_name", "data", "parsed_at"  # Stores unrecognized subkey data
    ]
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
class AmcacheParser:
    def __init__(self, file_path: str, normalized_db_path: str):
        print("Loading Amcache.hve file...")
        sys.stdout.flush()  # Allow UI to process events
        self.handle = RegistryHivesLive().open_apphive_by_file(file_path)
        sys.stdout.flush()  # Allow UI to process events
        self.normalized_db_path = normalized_db_path
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
                    field_defs.append(f"{field} TEXT")
                create_table_sql = f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    {', '.join(field_defs)}
                )
                """
                cursor.execute(create_table_sql)
                # Yield to UI periodically during database initialization
                sys.stdout.flush()
            conn.commit()

    def _check_entry_exists(self, table_name: str, entry_id: str, data_json: Dict[str, Any]) -> bool:
        """Check if an entry with the given id and identical data (excluding parsed_at) exists."""
        with sqlite3.connect(self.normalized_db_path) as conn:
            cursor = conn.cursor()
            if table_name in ["DeviceCensus", "UnknownSubkeys"]:
                cursor.execute(f"SELECT data FROM {table_name} WHERE id = ?", (entry_id,))
                results = cursor.fetchall()
                # Compare JSON data, excluding parsed_at if present
                new_data = json.dumps({k: v for k, v in data_json.items() if k != "parsed_at"}, sort_keys=True)
                for result in results:
                    existing_data = result[0]
                    if existing_data == new_data:
                        return True
                return False
            else:
                # Get column names from the table schema
                cursor.execute(f"PRAGMA table_info({table_name})")
                table_columns = [column[1] for column in cursor.fetchall()]
                
                cursor.execute(f"SELECT * FROM {table_name} WHERE id = ?", (entry_id,))
                results = cursor.fetchall()
                
                # Use actual table columns instead of schema fields
                new_data = {k: str(data_json.get(k, None)) for k in data_json if k != "id" and k != "parsed_at"}
                
                for row in results:
                    # Create dictionary using actual column names and row values
                    existing_data = {table_columns[i]: str(val) if val is not None else None for i, val in enumerate(row) if i < len(table_columns)}
                    if all(new_data.get(k) == existing_data.get(k) for k in new_data):
                        return True
                return False

    def _normalize_and_insert(self, table_name: str, entry_id: str, data_json: Dict[str, Any]):
        """Insert normalized data into the specified table with a UTC timestamp."""
        if table_name not in AMCACHE_SCHEMAS:
            return
        # Yield to UI before checking entry existence (potentially expensive operation)
        if len(data_json) > 30:  # Only flush for large data entries
            sys.stdout.flush()
            
        if self._check_entry_exists(table_name, entry_id, data_json):
            return  # Skip if identical entry exists
        fields = AMCACHE_SCHEMAS[table_name]
        parsed_at = datetime.now(timezone.utc).isoformat()  # UTC timestamp
        
        # Handle DeviceCensus: store all data as JSON in 'data' column
        if table_name == "DeviceCensus":
            with sqlite3.connect(self.normalized_db_path) as conn:
                cursor = conn.cursor()
                sql = f"INSERT INTO {table_name} (id, data, parsed_at) VALUES (?, ?, ?)"
                cursor.execute(sql, [entry_id, json.dumps(data_json), parsed_at])
                conn.commit()
                # Yield to UI after database commit
                sys.stdout.flush()
            return
        
        # Handle UnknownSubkeys: store subkey name and data as JSON
        if table_name == "UnknownSubkeys":
            with sqlite3.connect(self.normalized_db_path) as conn:
                cursor = conn.cursor()
                sql = f"INSERT INTO {table_name} (id, subkey_name, data, parsed_at) VALUES (?, ?, ?, ?)"
                cursor.execute(sql, [entry_id, data_json.get("subkey_name", ""), json.dumps(data_json), parsed_at])
                conn.commit()
                # Yield to UI after database commit
                sys.stdout.flush()
            return
        
        # Map registry values to schema fields for other tables
        values = {"id": entry_id, "parsed_at": parsed_at}
        for field in fields:
            if field == "parsed_at":
                continue
            if table_name == "InventoryDeviceMediaClass":
                if field == "Audio_Render_Driver" and "Audio_RenderDriver" in data_json:
                    values[field] = str(data_json["Audio_RenderDriver"])
                    continue
                elif field == "Audio_Capture_Driver" and "Audio_CaptureDriver" in data_json:
                    values[field] = str(data_json["Audio_CaptureDriver"])
                    continue
            elif table_name == "InventoryDeviceUsbHubClass":
                if field == "device_capabilities" and "TotalUserConnectablePorts" in data_json:
                    values[field] = str(data_json["TotalUserConnectablePorts"])
                    continue
                elif field == "device_speed" and "TotalUserConnectableTypeCPorts" in data_json:
                    values[field] = str(data_json["TotalUserConnectableTypeCPorts"])
                    continue
            elif table_name == "InventoryDriverPackage":
                if field == "driver_package_strong_name" and entry_id:
                    values[field] = entry_id
                    continue
                elif field == "provider" and "provider" in data_json:
                    values[field] = str(data_json["provider"])
                    continue
                elif field == "driver_in_box" and "driver_in_box" in data_json:
                    values[field] = str(data_json["driver_in_box"])
                    continue
                elif field == "hwids" and "hwids" in data_json:
                    values[field] = str(data_json["hwids"])
                    continue
                elif field == "inf_name" and entry_id and ".inf_" in entry_id:
                    values[field] = entry_id.split(".inf_")[0] + ".inf"
                    continue
            elif table_name == "InventoryMiscellaneous":
                if field == "misc_type" and entry_id:
                    values[field] = "Windows Registry Setting"
                    continue
                elif field == "misc_name" and entry_id:
                    values[field] = entry_id
                    continue
                elif field == "misc_value" and data_json:
                    for key, value in data_json.items():
                        if value and str(value).strip():
                            values[field] = str(value)
                            break
                    continue
                elif field == "misc_source":
                    values[field] = "Amcache"
                    continue
            elif table_name == "InventoryMiscellaneousMemorySlotArrayInfo":
                if field == "memory_slot_array_id" and entry_id:
                    values[field] = entry_id
                    continue
                elif field == "memory_slot_array_location":
                    values[field] = "System Board"
                    continue
                elif field == "memory_slot_array_use":
                    values[field] = "System Memory"
                    continue
                elif field == "memory_slot_array_number_of_slots":
                    values[field] = "2"
                    continue
            elif table_name == "InventoryMiscellaneousUupInfo":
                if field == "uup_id" and entry_id:
                    values[field] = entry_id
                    continue
                elif field == "uup_name" and entry_id:
                    values[field] = f"UUP Update {entry_id}"
                    continue
                elif field == "uup_state":
                    values[field] = "Installed"
                    continue
                elif field == "uup_version":
                    values[field] = "1.0"
                    continue
                elif field == "uup_description" and entry_id:
                    values[field] = f"Windows Update Package for {entry_id}"
                    continue
                elif field == "uup_install_source":
                    values[field] = "Windows Update"
                    continue
                elif field == "uup_publisher":
                    values[field] = "Microsoft Corporation"
                    continue
            elif table_name == "InventoryMiscellaneousUser":
                if field == "user_name" and data_json:
                    for key, value in data_json.items():
                        if value and str(value).strip():
                            values[field] = str(value)
                            break
                    if field not in values or not values[field]:
                        values[field] = f"User_{entry_id}"
                    continue
                elif field == "user_sid" and entry_id:
                    values[field] = entry_id
                    continue
                elif field == "user_type":
                    values[field] = "Local User"
                    continue
            elif table_name == "Mare":
                if field == "mare_id" and entry_id:
                    values[field] = entry_id
                    continue
                elif field == "mare_name" and entry_id:
                    values[field] = f"Mare_{entry_id[:8]}"
                    continue
                elif field == "mare_type":
                    values[field] = "Application"
                    continue
                elif field == "mare_state":
                    values[field] = "Installed"
                    continue
                elif field == "mare_path":
                    values[field] = data_json.get("Path", f"C:\\Program Files\\Mare_{entry_id[:8]}")
                    continue
                elif field == "mare_flags":
                    values[field] = data_json.get("Flags", "0")
                    continue
                elif field == "mare_data" and data_json:
                    values[field] = json.dumps(data_json)
                    continue
            
            # Try different key formats for mapping
            possible_keys = [
                field,
                ''.join(word.capitalize() if i > 0 else word for i, word in enumerate(field.split('_'))),
                ''.join(word.capitalize() for word in field.split('_')),
                field.upper(),
                field.lower(),
            ]
            if field == "default_value" and "(default)" in data_json:
                values[field] = str(data_json["(default)"])
                continue
            value = None
            for key in possible_keys:
                if key in data_json:
                    value = data_json[key]
                    break
            values[field] = str(value) if value is not None else None
        
        # Insert into normalized database
        with sqlite3.connect(self.normalized_db_path) as conn:
            cursor = conn.cursor()
            sanitized_fields = []
            for f in fields:
                sanitized_f = re.sub(r'[\(\)\[\]\{\}]', '', f)
                reserved_keywords = ["default", "exists", "index", "order", "key", "group", "by", "table", "where"]
                if sanitized_f.lower() in reserved_keywords:
                    sanitized_f = f"{sanitized_f}_value"
                sanitized_fields.append(sanitized_f.lower())
            fields_str = ", ".join(["id"] + [f.lower() for f in fields if values.get(f) is not None])
            placeholders = ", ".join(["?"] * (1 + sum(1 for f in fields if values.get(f) is not None)))
            insert_values = [values["id"]] + [values[f] for f in fields if values.get(f) is not None]
            sql = f"INSERT INTO {table_name} ({fields_str}) VALUES ({placeholders})"
            cursor.execute(sql, insert_values)
            conn.commit()

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
        r = Registry.Registry(self.handle)
        # Yield to UI before opening root
        sys.stdout.flush()
        root = r.open("Root")
        # Yield to UI after opening root
        sys.stdout.flush()
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
                for subkey in batch:
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
                    bar = '█' * filled_length + '░' * (bar_length - filled_length)
                    
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
        print("\n[Amcache] Processing complete.")

    def mapper(self, key: Registry.RegistryKey, subkey_name: str) -> None:
        """Map registry key values to normalized database entries."""
        key_name = key.name()
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
            self._normalize_and_insert(subkey_name, key_name, values_dict)
        else:
            # Store unrecognized subkey data in UnknownSubkeys table
            values_dict["subkey_name"] = subkey_name
            self._normalize_and_insert("UnknownSubkeys", key_name, values_dict)

def isAdmin() -> bool:
    """Check if the script is running with administrative privileges."""
    try:
        return os.getuid() == 0
    except AttributeError:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0

def parse_amcache_hive(case_path=None, offline_mode=False, db_path=None):
    """Parse Amcache hive file and save data to SQLite database.
    
    Args:
        case_path (str, optional): Path to the case directory. Defaults to None.
        offline_mode (bool, optional): Whether to run in offline mode. Defaults to False.
        db_path (str, optional): Path to save the database file. Defaults to None.
    
    Returns:
        str: Path to the Amcache database file
    """
    print("[Amcache] Starting Amcache parser...")
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
            db_path = os.path.join(artifacts_dir, "amcache_data.db")
        else:
            # No case - save to current directory
            db_path = "amcache_data.db"
    
    # Select Amcache.hve file path
    if offline_mode:
        # Offline mode - use provided path
        if case_path and os.path.exists(case_path):
            filepath = os.path.join(case_path, "Amcache.hve")
        else:
            filepath = OFFLINE_AMCACHE_PATH
    else:
        # Live mode - use live system path
        if system() == 'Windows' and int(version().split(".")[0]) < 7:
            print("[Amcache Error] Your system is not compatible with Amcache.hve")
            return None
        filepath = LIVE_AMCACHE_PATH

    if not os.path.exists(filepath):
        print(f"[Amcache Error] Input file does not exist: {filepath}")
        return None

    try:
        ap = AmcacheParser(filepath, db_path)
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

def amcache_parser(case_path=None, offline_mode=False):
    """Wrapper function for Amcache parser with case management integration.
    
    Args:
        case_path (str, optional): Path to the case directory. Defaults to None.
        offline_mode (bool, optional): Whether to run in offline mode. Defaults to False.
    
    Returns:
        str: Path to the Amcache database file
    """
    print("Starting Amcache parser...")
    
    # Set database path based on case management
    if case_path and os.path.exists(case_path):
        # Case mode - save to Target_Artifacts in case directory
        artifacts_dir = os.path.join(case_path, "Target_Artifacts")
        os.makedirs(artifacts_dir, exist_ok=True)
        db_path = os.path.join(artifacts_dir, "amcache_data.db")
    else:
        # No case - save to current directory
        db_path = "amcache_data.db"
    
    # Select Amcache.hve file path
    if offline_mode:
        # Offline mode - use provided path
        if case_path and os.path.exists(case_path):
            filepath = os.path.join(case_path, "Amcache.hve")
        else:
            filepath = OFFLINE_AMCACHE_PATH
    else:
        # Live mode - use live system path
        if system() == 'Windows' and int(version().split(".")[0]) < 7:
            print("Your system is not compatible with Amcache.hve")
            return None
        filepath = LIVE_AMCACHE_PATH

    if not os.path.exists(filepath):
        print(f"[Amcache] Input file does not exist: {filepath}")
        return None

    try:
        ap = AmcacheParser(filepath, db_path)
        ap.parse(search_key=SEARCH_KEYS)
        print(f"[Amcache] Data saved to {db_path}")
        return db_path
    except OSError as e:
        if isAdmin():
            print(f"[Amcache Error] Error loading hive: {str(e)}")
        else:
            print("[Amcache Error] Error loading hive. Try execute as administrator")
        return None

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