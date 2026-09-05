import hashlib
import sqlite3
try:
    import winreg
except ImportError:
    winreg = None
import os
import re
import datetime
import logging
import shutil
import ctypes
import platform
try:
    import win32security
    import win32api
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False
    logging.warning("win32security not available - user SID retrieval will be limited")
try:
    from Artifacts_Collectors import live_hive_access
    from Artifacts_Collectors import registry_hive_walk
    from Artifacts_Collectors import registry_extra_keys
except ModuleNotFoundError:                           # pragma: no cover
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from Artifacts_Collectors import live_hive_access
    from Artifacts_Collectors import registry_hive_walk
    from Artifacts_Collectors import registry_extra_keys

try:
    from Artifacts_Collectors import registry_binary_parser
except ModuleNotFoundError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from Artifacts_Collectors import registry_binary_parser

# Shared with the offline parser so both produce the same accounts and the same
# user names - see Artifacts_Collectors/user_identity.py
try:
    from Artifacts_Collectors import user_identity
except ModuleNotFoundError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from Artifacts_Collectors import user_identity

# Also shared with the offline parser - LSA policy, audit policy and secret
# metadata from the SECURITY hive.
try:
    from Artifacts_Collectors import security_hive
except ModuleNotFoundError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from Artifacts_Collectors import security_hive

# Import time utilities for standardized timestamp formatting
try:
    from utils.time_utils import format_forensic_timestamp, get_current_utc, filetime_to_datetime
except ModuleNotFoundError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.time_utils import format_forensic_timestamp, get_current_utc, filetime_to_datetime

# ---------------------------------------------------------------------------
# Class names and key security, which winreg does not expose.
#
# An nk record can carry a class name, a second string separate from the key's
# name; RegQueryInfoKeyW returns it and winreg.QueryInfoKey does not. The four
# keys under Control\Lsa keep the machine's boot key there, so a tool that
# reads names and values alone cannot see it at all.
#
# Both calls are declared with explicit argtypes. ctypes defaults an
# unspecified pointer argument to C int, which silently truncates a 64-bit
# handle - the sort of bug that returns plausible-looking nothing.
# ---------------------------------------------------------------------------

_ERROR_SUCCESS = 0
_ERROR_MORE_DATA = 234
_ERROR_INSUFFICIENT_BUFFER = 122

# Owner, group and the DACL. The SACL needs a privilege the parser does not
# take, and asking for it would fail the whole call rather than that part.
_SECURITY_WANTED = 0x00000001 | 0x00000002 | 0x00000004

try:
    import ctypes.wintypes as _wintypes

    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

    _RegQueryInfoKeyW = _advapi32.RegQueryInfoKeyW
    _RegQueryInfoKeyW.restype = _wintypes.LONG
    _RegQueryInfoKeyW.argtypes = [
        _wintypes.HKEY, _wintypes.LPWSTR, ctypes.POINTER(_wintypes.DWORD),
        ctypes.POINTER(_wintypes.DWORD), ctypes.POINTER(_wintypes.DWORD),
        ctypes.POINTER(_wintypes.DWORD), ctypes.POINTER(_wintypes.DWORD),
        ctypes.POINTER(_wintypes.DWORD), ctypes.POINTER(_wintypes.DWORD),
        ctypes.POINTER(_wintypes.DWORD), ctypes.POINTER(_wintypes.DWORD),
        ctypes.POINTER(_wintypes.FILETIME),
    ]

    _RegGetKeySecurity = _advapi32.RegGetKeySecurity
    _RegGetKeySecurity.restype = _wintypes.LONG
    _RegGetKeySecurity.argtypes = [
        _wintypes.HKEY, _wintypes.DWORD, ctypes.c_void_p,
        ctypes.POINTER(_wintypes.DWORD),
    ]
    KEY_METADATA_AVAILABLE = True
except Exception:                                       # pragma: no cover
    KEY_METADATA_AVAILABLE = False



# The documented value types, for naming a carved value's type. A carved cell
# can hold anything, including a type outside this set, which is why the lookup
# has a default rather than raising.
_REG_TYPE_NAMES = {
    0: "REG_NONE", 1: "REG_SZ", 2: "REG_EXPAND_SZ", 3: "REG_BINARY",
    4: "REG_DWORD", 5: "REG_DWORD_BIG_ENDIAN", 6: "REG_LINK",
    7: "REG_MULTI_SZ", 8: "REG_RESOURCE_LIST",
    9: "REG_FULL_RESOURCE_DESCRIPTOR", 10: "REG_RESOURCE_REQUIREMENTS_LIST",
    11: "REG_QWORD",
}



def _live_device_property_time(hive_path, enum_path, device, instance, pid):
    r"""One device property FILETIME, read from an acquired hive file.

    The device Properties keys deny winreg even elevated - a walk of Enum\USB
    through the API reaches 110 keys and is refused 21 subkeys, where the same
    hive read as a file reaches 868. So these are read from the file, and the
    API is not asked.

    Returns "" for anything missing rather than raising: a device without a
    removal date is a device that was never unplugged, which is ordinary.
    """
    if not hive_path:
        return ""
    try:
        from Registry import Registry as _Reg
        reg = _Reg.Registry(hive_path)
    except Exception:
        return ""

    guid = "{83da6326-97a6-4088-9453-a1923f573b29}"
    for control_set in ("ControlSet001", "ControlSet002", "ControlSet003"):
        path = "%s\\%s\\%s\\%s\\Properties\\%s\\%s" % (
            control_set, enum_path, device, instance, guid, pid)
        try:
            key = reg.open(path)
        except Exception:
            continue
        try:
            for value in key.values():
                try:
                    data = value.value()
                except Exception:
                    continue
                # python-registry hands back a datetime for
                # DEVPROP_TYPE_FILETIME; other readers give the raw eight bytes.
                if isinstance(data, datetime.datetime):
                    return format_forensic_timestamp(data)
                if isinstance(data, bytes) and len(data) >= 8:
                    try:
                        return format_forensic_timestamp(filetime_to_datetime(
                            int.from_bytes(data[:8], byteorder="little")))
                    except Exception:
                        continue
        except Exception:
            continue
    return ""



# What record_state says. A record recovered from a freed cell is marked
# wherever it appears, so an analyst reading any table knows this row was not
# in the live registry - rather than having to know which table means what.
#
# "(deleted)" describes where the record was found, not who removed it. Windows
# frees cells constantly by itself; a key in free space was removed, which is
# not the same as somebody having removed it.
DELETED_STATE = "(deleted)"
LIVE_STATE = "live"


def _carved_data_text(data, value_type):
    """A carved value's data, rendered so a person can read it.

    Text types are decoded; everything else becomes hex. Capped, because this
    is here to say what the value HELD, not to reconstitute a file out of free
    space - and because a parser writes to a console that is cp1252 by default,
    so the output has to stay ASCII.
    """
    if not data:
        return ""
    try:
        # REG_SZ, REG_EXPAND_SZ and REG_MULTI_SZ are UTF-16LE on disk.
        if value_type in (1, 2, 7):
            text = data.decode("utf-16-le", "replace").rstrip("\x00")
            text = text.replace("\x00", " | ").strip()
            printable = "".join(c if 32 <= ord(c) < 127 else "." for c in text)
            if printable.strip("."):
                return printable[:512]
        return data[:256].hex()
    except Exception:
        try:
            return data[:256].hex()
        except Exception:
            return ""


def _parser_allows_snapshot_creation():
    """May this parse CREATE a shadow copy, or only use ones that exist?

    Read from config/global_config.json directly. The parser runs headless
    under ParserInvoker as well as inside the GUI, so importing the settings
    dialog to read a setting would make it depend on a window that may not
    exist.

    Defaults to True, which is what the setting defaults to: a locked hive that
    cannot be read is evidence lost, and the analyst can turn it off in
    Settings -> Parsing when the machine must not be written to.
    """
    try:
        import json
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(os.path.dirname(here), "config", "global_config.json")
        if not os.path.exists(path):
            return True
        with open(path, "r", encoding="utf-8") as handle:
            return bool(json.load(handle).get("parser_allow_snapshot_creation", True))
    except Exception as exc:
        logging.debug("could not read the snapshot setting, defaulting to on: %s", exc)
        return True


def live_key_class(handle, initial=256):
    """The key's class name, '' when it has none, None when the call failed.

    The buffer is supplied up front. Passing NULL and reading back the length
    does not work here - the call has nothing to write and reports zero, which
    reads as "this key has no class" for every key on the machine.
    """
    if not KEY_METADATA_AVAILABLE:
        return None
    try:
        size = _wintypes.DWORD(initial)
        buf = ctypes.create_unicode_buffer(initial)
        rc = _RegQueryInfoKeyW(_wintypes.HKEY(handle), buf, ctypes.byref(size),
                               None, None, None, None, None, None, None, None, None)
        if rc == _ERROR_MORE_DATA:
            size = _wintypes.DWORD(size.value + 1)
            buf = ctypes.create_unicode_buffer(size.value)
            rc = _RegQueryInfoKeyW(_wintypes.HKEY(handle), buf, ctypes.byref(size),
                                   None, None, None, None, None, None, None, None, None)
        if rc != _ERROR_SUCCESS:
            return None
        return buf.value
    except Exception as e:
        logging.debug("class name read failed: %s", e)
        return None


def live_key_security(handle):
    """The key's self-relative security descriptor bytes, or None."""
    if not KEY_METADATA_AVAILABLE:
        return None
    try:
        size = _wintypes.DWORD(0)
        rc = _RegGetKeySecurity(_wintypes.HKEY(handle),
                                _wintypes.DWORD(_SECURITY_WANTED), None,
                                ctypes.byref(size))
        if rc not in (_ERROR_INSUFFICIENT_BUFFER, _ERROR_MORE_DATA, _ERROR_SUCCESS):
            return None
        if not size.value:
            return None
        buf = ctypes.create_string_buffer(size.value)
        rc = _RegGetKeySecurity(_wintypes.HKEY(handle),
                                _wintypes.DWORD(_SECURITY_WANTED),
                                ctypes.cast(buf, ctypes.c_void_p), ctypes.byref(size))
        if rc != _ERROR_SUCCESS:
            return None
        return buf.raw[:size.value]
    except Exception as e:
        logging.debug("key security read failed: %s", e)
        return None


def _configure_logging():
    try:
        usage = shutil.disk_usage(os.getcwd())
        free = usage.free
    except Exception:
        free = 0
    if free < 5 * 1024 * 1024:
        logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')
    else:
        logging.basicConfig(filename='regclaw_errors.log', level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')
_configure_logging()
def check_admin_privileges():
    """Check if the script is running with administrative privileges.
    
    Returns:
        bool: True if running as admin, False otherwise
    """
    if os.name == 'nt':
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except:
            return False
    else:
        try:
            return os.getuid() == 0
        except:
            return False

def require_admin_privileges():
    """Require administrative privileges or exit.
    
    This function should be called by operations that absolutely require admin access.
    For operations that can work with degraded functionality, use check_admin_privileges() instead.
    """
    if not check_admin_privileges():
        if os.name == 'nt':
            print("Error: This script requires administrative privileges.")
            print("Please run as Administrator to access all registry data.")
        else:
            print("Error: This operation requires root privileges on Linux.")
        exit(1)

def get_current_user_sid():
    """Get the SID of the current user.
    
    Returns:
        str: User SID string (e.g., "S-1-5-21-...") or empty string if unavailable
    """
    try:
        if not WIN32_AVAILABLE:
            logging.warning("win32security not available - cannot retrieve user SID")
            return ""
        
        # Get the current process token
        token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32security.TOKEN_QUERY)
        
        # Get the user SID from the token
        user_info = win32security.GetTokenInformation(token, win32security.TokenUser)
        user_sid = user_info[0]
        
        # Convert SID to string format
        sid_string = win32security.ConvertSidToStringSid(user_sid)
        
        return sid_string
        
    except Exception as e:
        logging.error(f"Error retrieving current user SID: {e}")
        return ""


def get_username_from_sid(sid_string):
    """Get the username associated with a SID.
    
    Args:
        sid_string (str): SID in string format (e.g., "S-1-5-21-...")
    
    Returns:
        str: Username or empty string if unavailable
    """
    try:
        if not WIN32_AVAILABLE or not sid_string:
            return ""
        
        # Convert string SID to SID object
        sid = win32security.ConvertStringSidToSid(sid_string)
        
        # Look up the account name
        name, domain, account_type = win32security.LookupAccountSid(None, sid)
        
        # Return domain\username format
        if domain:
            return f"{domain}\\{name}"
        return name
        
    except Exception as e:
        logging.debug(f"Could not resolve username for SID {sid_string}: {e}")
        return ""


def format_focus_time(milliseconds):
    """Convert milliseconds to human-readable format.
    
    Args:
        milliseconds (int): Time in milliseconds
    
    Returns:
        str: Formatted time string (e.g., "2.47h", "8.17m", "5.50s")
    """
    if milliseconds is None or milliseconds == 0:
        return "0s"
    
    seconds = milliseconds / 1000.0
    
    if seconds < 60:
        return f"{seconds:.2f}s"
    elif seconds < 3600:
        minutes = seconds / 60.0
        return f"{minutes:.2f}m"
    else:
        hours = seconds / 3600.0
        return f"{hours:.2f}h"


BS_SEP = chr(92)


def _ensure_columns(cursor, table_name, columns):
    """Add columns to a table that already exists, without rebuilding it.

    An existing case database is evidence. It gets ALTER TABLE ADD COLUMN and
    never a rebuild, so a re-parse of an old case gains the new columns and
    loses nothing that was already in it.

    `columns` is {name: sql_type}. Existing columns are left alone, and the
    comparison is case-insensitive because SQLite's are.
    """
    try:
        have = {row[1].lower()
                for row in cursor.execute('PRAGMA table_info("%s")' % table_name)}
    except Exception:
        return
    if not have:
        return                      # the table is not there yet; CREATE covers it
    for name, sql_type in columns.items():
        if name.lower() in have:
            continue
        try:
            cursor.execute('ALTER TABLE "%s" ADD COLUMN "%s" %s'
                           % (table_name, name, sql_type))
        except Exception as exc:                       # pragma: no cover
            logging.debug("could not add %s.%s: %s", table_name, name, exc)


# Columns added after these tables first shipped. Applied to every database the
# parser opens, new or existing, so the two never diverge.
DECODED_COLUMNS = {
    "time_zone": {"decoded": "TEXT"},
    "network_interfaces": {"decoded": "TEXT"},
    "Network_list": {"decoded": "TEXT", "parsed_at": "TEXT"},
    "BAM": {"decoded": "TEXT", "name_kind": "TEXT",
            "name_kind_raw": "INTEGER", "trailing_value": "INTEGER"},
    "DAM": {"decoded": "TEXT", "name_kind": "TEXT",
            "name_kind_raw": "INTEGER", "trailing_value": "INTEGER"},
    "TimeZoneInfo": {"daylight_bias": "INTEGER", "utc_offset": "TEXT",
                     "display_name": "TEXT", "standard_name_raw": "TEXT",
                     "daylight_name_raw": "TEXT",
                     "standard_start_rule": "TEXT",
                     "daylight_start_rule": "TEXT",
                     "dynamic_dst_disabled": "TEXT",
                     "agrees_with_tzi": "TEXT"},
    "NetworkInterfacesInfo": {"gateway_ip": "TEXT",
                              "gateway_hardware_mac": "TEXT",
                              "dns_suffix": "TEXT",
                              "lease_obtained": "TEXT",
                              "lease_expires": "TEXT"},
    # Which shell view wrote the bag. A shellbag records that a container was
    # rendered as a shell view, and Explorer is not the only thing that hosts
    # one - a File Open/Save dialog inside any program hosts one too, and
    # Windows files the two under different subkeys. Without these the table
    # cannot tell them apart, and a reader is left to assume a person browsed.
    "Shellbags": {"node_slot": "INTEGER", "bag_views": "TEXT"},
}


def apply_decoded_columns(cursor):
    """Bring every table up to the current column set."""
    for table, columns in DECODED_COLUMNS.items():
        _ensure_columns(cursor, table, columns)


def backfill_shellbag_view(cursor, file_name, registry_path, user_name,
                           node_slot, bag_views):
    """Fill a Shellbags row's view columns, only where they are still empty.

    A re-parse skips a row that is already there, which is what keeps the case
    from growing on every run. But a column added after the case was made is
    empty on every existing row, and skipping would leave it that way forever -
    the columns would only ever be populated on cases parsed after today.

    Guarded on `node_slot IS NULL`, so this adds information to a row and
    overwrites nothing that was already recorded. Called from the duplicate
    branch, and deliberately a function rather than four lines inline: the
    re-parse test reads the dozen lines above an INSERT looking for its
    check_exists guard, and inlining this pushed the guard out of that window.
    """
    try:
        cursor.execute(
            "UPDATE Shellbags SET node_slot = ?, bag_views = ? "
            "WHERE file_name IS ? AND registry_path IS ? AND user_name IS ? "
            "AND node_slot IS NULL",
            (node_slot, bag_views, file_name, registry_path, user_name))
    except Exception as exc:                             # pragma: no cover
        logging.debug("could not back-fill Shellbags view columns: %s", exc)


def check_exists(cursor, table_name, conditions, values):
    """Check if a record exists in the specified table based on conditions.
   
    Args:
        cursor: SQLite cursor object.
        table_name (str): Name of the table to check.
        conditions (list): List of column names to match (e.g., ['name', 'subkey']).
        values (tuple): Values to match for the conditions.
   
    Returns:
        bool: True if the record exists, False otherwise.
    """
    try:
        # `IS`, not `=`: SQL equality against NULL is never true, so a guard that
        # includes a column which is legitimately NULL - user_name on the HKCU
        # pass, before the ownership stamp runs - would never match, and every
        # re-parse would append the rows again. `IS` is NULL-safe and behaves
        # exactly like `=` for every other value.
        query = f"SELECT 1 FROM {table_name} WHERE {' AND '.join(f'{col} IS ?' for col in conditions)}"
        cursor.execute(query, values)
        return cursor.fetchone() is not None
    except Exception as e:
        logging.error(f"Error checking existence in {table_name}: {e}")
        return False
def parse_live_registry(case_root=None, db_path=None):
    """Parse registry from the live system and save to a database file.
   
    Args:
        case_root (str, optional): Path to the case root directory.
        db_path (str, optional): Custom path for the database file.
       
    Returns:
        str: Path to the created database file.
    """
    # Check administrative privileges (but don't require them)
    is_admin = check_admin_privileges()
    
    if not is_admin:
        print("=" * 80)
        print("WARNING: Not running with administrative privileges")
        print("=" * 80)
        print("Some registry data will not be accessible:")
        print("  - SAM user account data (login times, password changes, etc.)")
        print("  - Some system-level registry keys")
        print("\nBasic user profile information will still be collected.")
        print("For complete data, run as Administrator.")
        print("=" * 80)
        print()
   
    # Set the database filename based on the provided db_path or use default
    if db_path:
        db_filename = db_path
    else:
        db_filename = "registry_data.db" # Changed from registry_data_live.db to registry_data.db
   
    # Use case_root if provided
    if case_root:
        os.makedirs(case_root, exist_ok=True)
        artifacts_dir = os.path.join(case_root, "Target_Artifacts")
        os.makedirs(artifacts_dir, exist_ok=True)
        db_filename = os.path.join(artifacts_dir, os.path.basename(db_filename))
   
    # Call the main registry collection function with the database path
    return main_live_reg(db_filename)
def main_live_reg(db_filename='registry_data.db'):
    """Main function for live registry parsing with comprehensive error handling"""
    try:
        # Function to read registry values and their types from a live system
        def _read_values_at(hive_key, key_path):
            try:
                values = {}
                with winreg.OpenKey(hive_key, key_path) as key:
                    i = 0
                    while True:
                        try:
                            name, data, value_type = winreg.EnumValue(key, i)
                            # Convert value_type to string representation
                            value_type_str = {
                                winreg.REG_SZ: "REG_SZ",
                                winreg.REG_EXPAND_SZ: "REG_EXPAND_SZ",
                                winreg.REG_BINARY: "REG_BINARY",
                                winreg.REG_DWORD: "REG_DWORD",
                                winreg.REG_QWORD: "REG_QWORD",
                                winreg.REG_MULTI_SZ: "REG_MULTI_SZ",
                                winreg.REG_NONE: "REG_NONE"
                            }.get(value_type, "UNKNOWN")
                            # Keep binary data as bytes for proper parsing later
                            # Don't convert REG_BINARY to string here - let specialized parsers handle it
                           
                            values[name] = (data, value_type_str)
                            i += 1
                        except WindowsError:
                            break
                return values
            except FileNotFoundError:
                # Key doesn't exist - this is expected for some optional keys like DAM UserSettings
                logging.debug(f"Registry key not found (expected for some systems): {key_path}")
                return {}
            except Exception as e:
                logging.error(f"Error reading registry key {key_path}: {e}")
                return {}
        
        # Function to get subkeys and their values
        def _read_subkeys_at(hive_key, key_path):
            try:
                subkey_values = {}
                with winreg.OpenKey(hive_key, key_path) as key:
                    # Get number of subkeys
                    subkey_count = winreg.QueryInfoKey(key)[0]
                    # Enumerate subkeys
                    for i in range(subkey_count):
                        subkey_name = winreg.EnumKey(key, i)
                        subkey_path = f"{key_path}\\{subkey_name}"
                        # Get values for this subkey
                        subkey_values[subkey_name] = {}
                        try:
                            with winreg.OpenKey(hive_key, subkey_path) as subkey:
                                j = 0
                                while True:
                                    try:
                                        name, data, value_type = winreg.EnumValue(subkey, j)
                                        # Convert value_type to string representation
                                        value_type_str = {
                                            winreg.REG_SZ: "REG_SZ",
                                            winreg.REG_EXPAND_SZ: "REG_EXPAND_SZ",
                                            winreg.REG_BINARY: "REG_BINARY",
                                            winreg.REG_DWORD: "REG_DWORD",
                                            winreg.REG_QWORD: "REG_QWORD",
                                            winreg.REG_MULTI_SZ: "REG_MULTI_SZ",
                                            winreg.REG_NONE: "REG_NONE"
                                        }.get(value_type, "UNKNOWN")
                                        # Keep binary data as bytes - don't convert here
                                        # Let specialized parsers handle binary data conversion
                                       
                                        subkey_values[subkey_name][name] = (data, value_type_str)
                                        j += 1
                                    except WindowsError:
                                        break
                                try:
                                    default_data, default_type = winreg.QueryValueEx(subkey, "")
                                    default_type_str = {
                                        winreg.REG_SZ: "REG_SZ",
                                        winreg.REG_EXPAND_SZ: "REG_EXPAND_SZ",
                                        winreg.REG_BINARY: "REG_BINARY",
                                        winreg.REG_DWORD: "REG_DWORD",
                                        winreg.REG_QWORD: "REG_QWORD",
                                        winreg.REG_MULTI_SZ: "REG_MULTI_SZ",
                                        winreg.REG_NONE: "REG_NONE"
                                    }.get(default_type, "UNKNOWN")
                                    subkey_values[subkey_name]["(Default)"] = (default_data, default_type_str)
                                except Exception:
                                    pass
                        except Exception as e:
                            logging.debug(f"Error reading subkey {subkey_path}: {e}")
                return subkey_values
            except FileNotFoundError:
                # Key doesn't exist - this is expected for some optional keys like DAM UserSettings
                logging.debug(f"Registry key not found (expected for some systems): {key_path}")
                return {}
            except Exception as e:
                logging.error(f"Error reading subkeys for {key_path}: {e}")
                return {}
        
        # ------------------------------------------------------- ControlSets
        # CurrentControlSet is an alias Windows resolves to whichever set is
        # active, so reading through it sees exactly one of them. A machine
        # normally carries two - the active one and LastKnownGood - and they can
        # differ: a service disabled since the last successful boot is still
        # enabled in the other set, which is the kind of thing an analyst wants.
        # The offline parser has always merged ControlSet001/002/003, so on any
        # machine with more than one the two parsers silently disagreed. This
        # machine has one, which is why the content audit never caught it.
        _controlsets_cache = []

        def _controlsets():
            """Every ControlSet00N present, the active one first. Cached."""
            if _controlsets_cache:
                return _controlsets_cache
            active = None
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\Select") as _sel:
                    active = "ControlSet%03d" % int(winreg.QueryValueEx(_sel, "Current")[0])
            except Exception as e:
                logging.debug("SYSTEM\\Select unreadable: %s", e)
            found = []
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, "SYSTEM") as _sys:
                    for _i in range(winreg.QueryInfoKey(_sys)[0]):
                        _n = winreg.EnumKey(_sys, _i)
                        if _n.lower().startswith("controlset"):
                            found.append(_n)
                    found.sort()
            except Exception as e:
                logging.debug("SYSTEM subkeys unreadable: %s", e)
            if active and active in found:
                found.remove(active)
                found.insert(0, active)
            elif not found:
                # Nothing enumerable: fall back to the alias so the parser still
                # reads the active set rather than nothing at all.
                found = ["CurrentControlSet"]
            _controlsets_cache.extend(found)
            return _controlsets_cache

        def _cs_paths(subpath):
            r"""`SYSTEM\<set>\<subpath>` for every ControlSet, active first."""
            tail = (subpath or "").lstrip("\\")
            return ["SYSTEM\\" + cs + ("\\" + tail if tail else "")
                    for cs in _controlsets()]

        _CCS_PREFIX = "system" + chr(92) + "currentcontrolset"

        def _cs_expand(key_path):
            """Concrete per-ControlSet paths for a CurrentControlSet path.

            Returns [] for anything else, which is how the dispatchers below
            tell "merge this" from "read it as given".
            """
            low = (key_path or "").lower()
            if not low.startswith(_CCS_PREFIX):
                return []
            tail = key_path[len(_CCS_PREFIX):].lstrip(chr(92))
            return _cs_paths(tail)

        def reg_Claw_live(hive_key, key_path):
            """Values of a key. A CurrentControlSet path reads every ControlSet.

            Reading through the CurrentControlSet alias sees exactly one set.
            Merging here rather than at fifty call sites means no reader can be
            forgotten, and the active set is applied last so it wins.
            """
            paths = (_cs_expand(key_path)
                     if hive_key == winreg.HKEY_LOCAL_MACHINE else [])
            if not paths:
                return _read_values_at(hive_key, key_path)
            merged = {}
            for path in reversed(paths):
                merged.update(_read_values_at(hive_key, path) or {})
            return merged

        def get_subkeys_live(hive_key, key_path):
            """Subkeys of a key, merged across ControlSets on a SYSTEM path.

            A service present in LastKnownGood but not in the active set is a
            real finding, and reading one set could not show it.
            """
            paths = (_cs_expand(key_path)
                     if hive_key == winreg.HKEY_LOCAL_MACHINE else [])
            if not paths:
                return _read_subkeys_at(hive_key, key_path)
            merged = {}
            for path in reversed(paths):
                for name, values in (_read_subkeys_at(hive_key, path) or {}).items():
                    merged.setdefault(name, {}).update(values or {})
            return merged

        def key_last_write_live(hive_key, key_path):
            """The key's own last-write time, formatted UTC, or '' if unreadable.

            For an MRU key this is the artifact's only timestamp: RecentDocs
            stores no per-value time, so the last write on `RecentDocs\\.pdf` is
            when a PDF was most recently opened. QueryInfoKey returns a FILETIME
            in 100ns units, which filetime_to_datetime converts to UTC - the same
            value python-registry reads off the NK record offline, so both
            parsers report one time for one key.
            """
            try:
                with winreg.OpenKey(hive_key, key_path) as _k:
                    ft = winreg.QueryInfoKey(_k)[2]
                    if not ft:
                        return ""
                    return format_forensic_timestamp(filetime_to_datetime(ft))
            except Exception as e:
                logging.debug(f"No last-write time for {key_path}: {e}")
                return ""

        def mru_order_live(values):
            """Access order from an MRUListEx value, [] when there is none.

            The list itself is never stored as a row - it is ordering, not
            evidence - but it is the only record of which entry is most recent.
            """
            for _n, (_d, _t) in (values or {}).items():
                if _n.lower() == 'mrulistex' and isinstance(_d, bytes):
                    try:
                        return registry_binary_parser.parse_mru_list_ex(_d)
                    except Exception as e:
                        logging.debug(f"MRUListEx unreadable: {e}")
                    break
            return []

        # Define registry hive constants
        HKEY_CURRENT_USER = winreg.HKEY_CURRENT_USER
        HKEY_LOCAL_MACHINE = winreg.HKEY_LOCAL_MACHINE
        # Define paths for Run, RunOnce, DAM, and BAM keys
        paths = {
            "machine_run": (HKEY_LOCAL_MACHINE, "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run"),
            "machine_run_once": (HKEY_LOCAL_MACHINE, "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\RunOnce"),
            "user_run": (HKEY_CURRENT_USER, "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run"),
            "user_run_once": (HKEY_CURRENT_USER, "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\RunOnce"),
            "dam": (HKEY_LOCAL_MACHINE, "SYSTEM\\CurrentControlSet\\Services\\dam\\UserSettings"),
            "bam": (HKEY_LOCAL_MACHINE, "SYSTEM\\CurrentControlSet\\Services\\bam\\State\\UserSettings")
        }
        # Define table name mapping
        table_name_mapping = {
            "machine_run": "machine_run",
            "machine_run_once": "machine_run_once",
            "user_run": "user_run",
            "user_run_once": "user_run_once",
            "dam": "DAM",
            "bam": "BAM"
        }
        # Use the provided database filename
        # No need to override the db_filename as it's passed as a parameter
        timestamp = get_current_utc().strftime("%Y%m%d_%H%M%S")
        # Who is this parse running as? Resolved up front, because the HKCU
        # collectors below have to stamp user_name at INSERT time.
        #
        # Writing NULL and back-filling it later looks equivalent and is not: the
        # ownership UPDATE runs at the end of the parse, so on the SECOND parse
        # the guards - which include user_name - no longer match the rows they
        # wrote the first time, and every one of them is inserted again. Shellbags
        # and MUICache doubled exactly that way.
        try:
            _live_user = get_username_from_sid(get_current_user_sid()) or None
        except Exception as e:
            logging.warning(f"Could not resolve the current user: {e}")
            _live_user = None

        # Connect to SQLite database (or create it if it doesn't exist)
        with sqlite3.connect(db_filename) as conn:
            cursor = conn.cursor()

            # The expansion environment, read from the machine being parsed.
            # `%SystemRoot%\system32\...` is stored unexpanded in dozens of
            # ASEP values; expanding it needs the SystemRoot of the EVIDENCE,
            # which for a live parse is this machine and for an image is not.
            # Read from the registry rather than os.environ so the offline
            # parser can hand in its own without the decoder caring which.
            _evidence_env = {}
            try:
                for _env_name in ("SystemRoot", "ProgramFilesDir",
                                  "CommonFilesDir", "ProgramFilesDir (x86)"):
                    try:
                        _env_val, _ = winreg.QueryValueEx(
                            winreg.OpenKey(
                                winreg.HKEY_LOCAL_MACHINE,
                                r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"),
                            _env_name)
                    except OSError:
                        continue
                    if _env_val:
                        _evidence_env[_env_name] = str(_env_val)
                if "SystemRoot" in _evidence_env:
                    # windir is the same directory under its other name, and it
                    # is by far the commonest spelling in these values - 978
                    # uses against 27 for %SystemRoot% on the reference system.
                    _evidence_env.setdefault("windir", _evidence_env["SystemRoot"])
                    _drive = os.path.splitdrive(_evidence_env["SystemRoot"])[0]
                    if _drive:
                        _evidence_env.setdefault("SystemDrive", _drive)
                # ProgramData and Public come from the shell folder key that
                # defines them, so an image that puts them somewhere unusual
                # is read as it actually is.
                try:
                    _sf = winreg.OpenKey(
                        winreg.HKEY_LOCAL_MACHINE,
                        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer"
                        r"\Shell Folders")
                    for _sf_name, _env_key in (("Common AppData", "ProgramData"),
                                               ("Public", "PUBLIC")):
                        try:
                            _sf_val, _ = winreg.QueryValueEx(_sf, _sf_name)
                        except OSError:
                            continue
                        if _sf_val:
                            _evidence_env.setdefault(_env_key, str(_sf_val))
                    if "ProgramData" in _evidence_env:
                        _evidence_env.setdefault(
                            "ALLUSERSPROFILE", _evidence_env["ProgramData"])
                except OSError:
                    pass
            except Exception as _env_exc:
                logging.debug("evidence environment: %s", _env_exc)

            # Additive migration for the three oldest tables, which gained
            # row_decoded. Their DDL is a (name, DDL) tuple entry and so is
            # CREATE TABLE IF NOT EXISTS - a no-op on a case already written.
            for _rd_t in ('machine_run', 'shutdown_information',
                          'Windows_lastupdate_subkeys'):
                try:
                    cursor.execute('PRAGMA table_info(%s)' % _rd_t)
                    if 'row_decoded' not in [c[1] for c in cursor.fetchall()]:
                        cursor.execute(
                            'ALTER TABLE %s ADD COLUMN row_decoded TEXT' % _rd_t)
                except sqlite3.Error as _rd_mig:
                    logging.debug('row_decoded migration %s: %s', _rd_t, _rd_mig)

            def _row_decoded(table, name, data, vtype=None):
                """The decoded form of a plain name/row_data value, or "".

                The same decoder every other table uses. These three are
                written 1,500 lines before the ASEP pass, which is why the
                environment above is built here rather than there.
                """
                try:
                    got = registry_binary_parser.render_registry_value(
                        table, name, data, vtype, _evidence_env) or ''
                except Exception:
                    return ''
                return '' if got == str(data) else got

            # Create tables if they don't exist (original tables for backward compatibility)
            tables = [
                ("machine_run", "name TEXT, row_data TEXT, row_decoded TEXT, type TEXT"),
                ("machine_run_once", "name TEXT, row_data TEXT, type TEXT"),
                ("user_run", "name TEXT, row_data TEXT, type TEXT"),
                ("user_run_once", "name TEXT, row_data TEXT, type TEXT"),
                ("Windows_lastupdate", "name TEXT, row_data TEXT, type TEXT"),
                ("Windows_lastupdate_subkeys", "subkey TEXT, name TEXT, row_data TEXT, row_decoded TEXT, type TEXT"),
                ("computer_Name", "name TEXT, row_data TEXT, type TEXT"),
                ("time_zone", "name TEXT, row_data TEXT, decoded TEXT, type TEXT"),
                ("network_interfaces", "subkey TEXT, name TEXT, row_data TEXT, decoded TEXT, type TEXT"),
                ("shutdown_information", "name TEXT, row_data TEXT, row_decoded TEXT, type TEXT")
            ]
            for table_name, schema in tables:
                cursor.execute(f'CREATE TABLE IF NOT EXISTS {table_name} ({schema})')
            # Create more detailed tables for specific registry sections
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS ComputerNameInfo (
                computer_name TEXT,
                registered_owner TEXT,
                registered_organization TEXT,
                product_id TEXT,
                installation_date TEXT,
                parsed_at TEXT
            )''')
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS TimeZoneInfo (
                time_zone_name TEXT,
                standard_name TEXT,
                daylight_name TEXT,
                bias INTEGER,
                active_time_bias INTEGER,
                daylight_bias INTEGER,
                utc_offset TEXT,
                display_name TEXT,
                standard_name_raw TEXT,
                daylight_name_raw TEXT,
                standard_start_rule TEXT,
                daylight_start_rule TEXT,
                dynamic_dst_disabled TEXT,
                agrees_with_tzi TEXT,
                parsed_at TEXT
            )''')
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS NetworkInterfacesInfo (
                interface_id TEXT,
                ip_address TEXT,
            subnet_mask TEXT,
            default_gateway TEXT,
            dhcp_enabled INTEGER,
            dhcp_server TEXT,
            dns_servers TEXT,
            mac_address TEXT,
            gateway_ip TEXT,
            gateway_hardware_mac TEXT,
            dns_suffix TEXT,
            lease_obtained TEXT,
            lease_expires TEXT,
            parsed_at TEXT
            )''')
            # 'Auto' used to be created here. It was never written to - zero
            # inserts, zero rows in every case database - and every column it
            # declared is already carried by WindowsUpdateInfo below. Creating a
            # table nothing fills makes an empty tab look like an artifact with
            # no findings, which is not the same thing.
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS WindowsUpdateInfo (
            last_check_time TEXT,
            last_install_time TEXT,
            au_options INTEGER,
            scheduled_install_day INTEGER,
            scheduled_install_time INTEGER,
            parsed_at TEXT
            )''')
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS ShutdownInfo (
            shutdown_time TEXT,
            shutdown_count INTEGER,
            shutdown_type TEXT,
            clean_shutdown INTEGER,
            parsed_at TEXT
            )''')
            # Created here too, and deliberately left empty on a live parse.
            #
            # The offline parser fills this with one row per hive: whether
            # Windows had it open mid-transaction and whether its .LOG1/.LOG2
            # were replayed. A live parse reads the running registry through
            # winreg - there is no hive file, so there is nothing that can be
            # stale, and no row to write.
            #
            # The table still exists so a case has the same shape whichever way
            # it was parsed. An analyst who queries registry_hive_state on a
            # live case gets "no rows", which is the true answer; a missing
            # table would look like an older build instead.
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS registry_hive_state (
            hive_name TEXT,
            hive_path TEXT,
            sequence_1 INTEGER,
            sequence_2 INTEGER,
            was_dirty INTEGER,
            logs_found TEXT,
            log_format TEXT,
            replayed INTEGER,
            entries_applied INTEGER,
            pages_applied INTEGER,
            highest_sequence INTEGER,
            source_sha256 TEXT,
            acquisition_route TEXT,
            reason TEXT,
            parsed_at TEXT
            )''')

            # Additive migration: a case database from an earlier build has
            # this table without source_sha256, and CREATE TABLE IF NOT EXISTS
            # will not add it. Kept identical to the offline parser's, because
            # the whole point of creating this table on a live parse is that
            # both routes produce a case of the same shape.
            try:
                cursor.execute("PRAGMA table_info(registry_hive_state)")
                _hs_cols = [c[1] for c in cursor.fetchall()]
                if _hs_cols and "source_sha256" not in _hs_cols:
                    cursor.execute("ALTER TABLE registry_hive_state "
                                   "ADD COLUMN source_sha256 TEXT")
                if _hs_cols and "acquisition_route" not in _hs_cols:
                    cursor.execute("ALTER TABLE registry_hive_state "
                                   "ADD COLUMN acquisition_route TEXT")
            except sqlite3.Error as _e:
                logging.debug("source_sha256 migration (live): %s", _e)
            # ---- what a tree walk cannot see ------------------------
            # Sections 13 and 14 of the registry guide. Class names and
            # security descriptors are read live through advapi32; carving has
            # no live equivalent, so those two tables are created and left
            # empty exactly as registry_hive_state is, and a case has the same
            # shape whichever way it was acquired.
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS registry_class_names (
            hive_name TEXT,
            key_path TEXT,
            key_name TEXT,
            class_name TEXT,
            class_length INTEGER,
            key_last_write TEXT,
            parsed_at TEXT,
            UNIQUE(hive_name, key_path, class_name)
            )''')

            cursor.execute('''
            CREATE TABLE IF NOT EXISTS registry_security_descriptors (
            hive_name TEXT,
            sk_offset INTEGER,
            descriptor_hash TEXT,
            reference_count INTEGER,
            owner_sid TEXT,
            group_sid TEXT,
            dacl_ace_count INTEGER,
            sacl_ace_count INTEGER,
            descriptor_size INTEGER,
            sample_key_path TEXT,
            parsed_at TEXT,
            UNIQUE(hive_name, descriptor_hash)
            )''')

            # Created, and deliberately left empty on a live parse: carving
            # reads freed cells out of a hive FILE, and a live read goes
            # through the API, which has no concept of one.
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS registry_carved_keys (
            hive_name TEXT,
            cell_offset INTEGER,
            key_name TEXT,
            key_path TEXT,
            parent_resolved INTEGER,
            key_last_write TEXT,
            subkey_count INTEGER,
            value_count INTEGER,
            record_state TEXT,
            parsed_at TEXT,
            UNIQUE(hive_name, cell_offset)
            )''')

            cursor.execute('''
            CREATE TABLE IF NOT EXISTS registry_carved_values (
            hive_name TEXT,
            cell_offset INTEGER,
            parent_cell_offset INTEGER,
            key_path TEXT,
            value_name TEXT,
            value_type TEXT,
            data_size INTEGER,
            is_inline INTEGER,
            data TEXT,
            record_state TEXT,
            parsed_at TEXT,
            UNIQUE(hive_name, cell_offset)
            )''')

            # Enhanced tables for USB devices
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS USBDevices (
            device_id TEXT PRIMARY KEY,
            description TEXT,
            manufacturer TEXT,
            friendly_name TEXT,
            last_connected TEXT
            )''')
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS USBProperties (
            device_id TEXT,
            property_name TEXT,
            property_value TEXT,
            property_type TEXT,
            PRIMARY KEY (device_id, property_name)
            )''')
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS USBInstances (
            device_id TEXT,
            instance_id TEXT,
            parent_id TEXT,
            service TEXT,
            status TEXT,
            PRIMARY KEY (device_id, instance_id)
            )''')
            # Enhanced tables for USB storage devices
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS USBStorageDevices (
            device_id TEXT PRIMARY KEY,
            friendly_name TEXT,
            serial_number TEXT,
            vendor_id TEXT,
            product_id TEXT,
            revision TEXT,
            first_connected TEXT,
            last_connected TEXT,
            last_removed TEXT,
            parsed_at TEXT
            )''')
            try:
                cursor.execute('ALTER TABLE USBStorageDevices ADD COLUMN last_removed TEXT')
            except Exception:
                pass
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS USBStorageVolumes (
                device_id TEXT,
                volume_guid TEXT,
                volume_name TEXT,
                drive_letter TEXT,
                parsed_at TEXT,
                PRIMARY KEY (device_id, volume_guid)
        )''')
        # Enhanced table for browser history
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS BrowserHistory (
            browser TEXT,
            url TEXT,
            title TEXT,
            visit_count INTEGER,
            last_visit TEXT,
            parsed_at TEXT,
            user_name TEXT
        )''')
        # Whether each autostart entry is allowed to launch, and when it was switched off.
        # Without this a persistence table lists everything the Run key holds as though it all ran.
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS startup_approved (
                hive TEXT, scope TEXT, entry_name TEXT, state TEXT, state_byte TEXT,
                disabled_at TEXT, key_path TEXT, last_written TEXT, time_basis TEXT,
                parsed_at TEXT,
                UNIQUE(hive, scope, entry_name)
        )''')

        # How a bare command name resolves to an executable.
        # A hijack point: change the entry and typing the name runs something else.
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS app_paths (
                app_name TEXT, executable_path TEXT, app_dir TEXT, key_path TEXT,
                last_written TEXT, time_basis TEXT, parsed_at TEXT,
                UNIQUE(app_name)
        )''')

        # Services and drivers that still start in Safe Mode.
        # Persistence placed here survives the boot most people use to clean a machine.
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS safe_boot_services (
                boot_mode TEXT, entry_name TEXT, entry_type TEXT, key_path TEXT,
                last_written TEXT, time_basis TEXT, parsed_at TEXT,
                UNIQUE(boot_mode, entry_name)
        )''')

        # Sites and domains assigned to an Internet Explorer security zone.
        # A host moved into Trusted Sites runs content the others would block.
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS zone_map (
                scope TEXT, host TEXT, protocol TEXT, zone TEXT, zone_name TEXT,
                key_path TEXT, last_written TEXT, time_basis TEXT, parsed_at TEXT,
                UNIQUE(scope, host, protocol)
        )''')

        # Which applications hold consent for a capability - microphone, camera, location - and when each last used it..
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS app_permissions (
                capability TEXT, app TEXT, packaged INTEGER, permission TEXT,
                last_used_start TEXT, last_used_stop TEXT, key_path TEXT,
                last_written TEXT, time_basis TEXT, parsed_at TEXT,
                UNIQUE(capability, app)
        )''')

        # Reference counts Windows keeps for shared libraries.
        # Mostly inventory, and occasionally the only record that a DLL was ever installed.
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS shared_dlls (
                dll_path TEXT, reference_count INTEGER, key_path TEXT,
                last_written TEXT, time_basis TEXT, parsed_at TEXT,
                UNIQUE(dll_path)
        )''')

        # Human interface devices the machine has enumerated - keyboards, mice and anything that presents itself as one..
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS hid_devices (
                device_id TEXT, instance_id TEXT, device_desc TEXT, manufacturer TEXT,
                service TEXT, key_path TEXT, last_written TEXT, time_basis TEXT,
                parsed_at TEXT,
                UNIQUE(device_id, instance_id)
        )''')

        # The adapter inventory, by installation index.
        # Names cards that no longer have an interface.
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS network_cards (
                card_index TEXT, description TEXT, service_name TEXT, key_path TEXT,
                last_written TEXT, time_basis TEXT, parsed_at TEXT,
                UNIQUE(card_index)
        )''')

        # Settings rather than artifacts: power and fast startup, locale, time source, TCP/IP identity, search scope, shell folders and the taskbar.
        # Same shape as SecurityPosture, which holds the security-relevant subset.
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS system_configuration (
                setting TEXT, value_raw TEXT, value_decoded TEXT, area TEXT,
                meaning TEXT, key_path TEXT, last_written TEXT, time_basis TEXT,
                parsed_at TEXT,
                UNIQUE(area, setting, key_path)
        )''')
        # Enhanced table for installed software
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS registry_value_changes (
            hive_name TEXT, transaction_sequence INTEGER, change_kind TEXT,
            changed_at TEXT, key_path TEXT, value_name TEXT, value_type TEXT,
            changed_before TEXT, changed_after TEXT, value_before TEXT,
            changed_bytes INTEGER, cell_offset INTEGER, key_last_write TEXT,
            parsed_at TEXT,
            UNIQUE(hive_name, transaction_sequence, key_path, value_name)
        )''')

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS registry_key_times (
            hive_name TEXT, key_path TEXT, key_last_write TEXT,
            cell_offset INTEGER, parsed_at TEXT,
            UNIQUE(hive_name, key_path)
        )''')

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS InstalledSoftware (
            display_name TEXT,
            display_version TEXT,
            publisher TEXT,
            install_date TEXT,
            install_location TEXT,
            uninstall_string TEXT,
            parsed_at TEXT
        )''')
        # Enhanced table for system services
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS SystemServices (
            service_name TEXT PRIMARY KEY,
            display_name TEXT,
            description TEXT,
            image_path TEXT,
            start_type INTEGER,
            service_type INTEGER,
            error_control INTEGER,
            status TEXT,
            parsed_at TEXT
        )''')
        # Create table for auto start programs
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS AutoStartPrograms (
            location TEXT,
            program_name TEXT,
            command TEXT,
            key_path TEXT,
            startup_state TEXT,
            disabled_at TEXT,
            record_state TEXT,
        last_written TEXT, time_basis TEXT,
            parsed_at TEXT,
            PRIMARY KEY (location, program_name)
        )''')
        # Enhanced DAM and BAM tables with detailed process information
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS DAM (
            subkey TEXT,
            name TEXT,
            row_data TEXT,
            type TEXT,
            app_name TEXT,
            process_path TEXT,
            sid TEXT,
            last_execution TEXT,
            execution_count INTEGER,
            decoded TEXT,
            name_kind TEXT,
            name_kind_raw INTEGER,
            trailing_value INTEGER,
        last_written TEXT, time_basis TEXT,
            parsed_at TEXT
        )''')
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS BAM (
            subkey TEXT,
            name TEXT,
            row_data TEXT,
            type TEXT,
            app_name TEXT,
            process_path TEXT,
            sid TEXT,
            last_execution TEXT,
            decoded TEXT,
            name_kind TEXT,
            name_kind_raw INTEGER,
            trailing_value INTEGER,
        last_written TEXT, time_basis TEXT,
            parsed_at TEXT
        )''')
        # WordWheelQuery table for Windows Explorer search history
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS WordWheelQuery (
            search_term TEXT,
            search_type TEXT,
            mru_position INTEGER,
            access_date TEXT,
            key_last_write TEXT,
            parsed_at TEXT,
            user_name TEXT
        )''')
        # UserAssist table for program execution tracking
        # user_sid now contains the actual Windows user SID (e.g., S-1-5-21-...)
        # instead of the UserAssist GUID, providing proper user attribution
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS UserAssist (
            program_path TEXT,
            run_count INTEGER,
            last_execution TEXT,
            focus_count INTEGER,
            focus_time INTEGER,
            user_sid TEXT,
            parsed_at TEXT
        )''')
        # Shellbags table for folder access history (enhanced with additional metadata)
        # Check if old schema exists and migrate if needed
        cursor.execute("PRAGMA table_info(Shellbags)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if columns and 'timestamp' in columns and 'parsed_at' not in columns:
            # Migration needed - old schema exists
            logging.info("Migrating Shellbags table to new schema...")
            
            # Create new table with updated schema
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS Shellbags_new (
                file_name TEXT,
                short_name TEXT,
                shell_item_type TEXT,
                mru_position TEXT,
                created_date TEXT,
                modified_date TEXT,
                accessed_date TEXT,
                attributes TEXT,
                file_size INTEGER DEFAULT 0,
                special_folder TEXT,
                network_share TEXT,
                server_name TEXT,
                share_name TEXT,
                drive_letter TEXT,
                mft_record_number INTEGER,
                registry_path TEXT,
        last_written TEXT, time_basis TEXT,
                parsed_at TEXT
            )''')
            
            # Copy existing data (folder_name becomes file_name, mru_position becomes TEXT)
            cursor.execute('''INSERT INTO Shellbags_new 
                (file_name, shell_item_type, mru_position, 
                 created_date, modified_date, accessed_date, attributes, 
                 file_size, special_folder, network_share, registry_path, parsed_at)
                SELECT folder_name, shell_item_type, 
                       CAST(mru_position AS TEXT), 
                       created_date, modified_date, access_date, attributes, 
                       file_size, special_folder, network_share, registry_path, timestamp
                FROM Shellbags''')
            
            # Drop old table and rename new one
            cursor.execute('DROP TABLE Shellbags')
            cursor.execute('ALTER TABLE Shellbags_new RENAME TO Shellbags')
            
            logging.info("Shellbags table migration completed")
        elif not columns:
            # No existing table, create new schema
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS Shellbags (
                file_name TEXT,
                short_name TEXT,
                shell_item_type TEXT,
                mru_position TEXT,
                created_date TEXT,
                modified_date TEXT,
                accessed_date TEXT,
                attributes TEXT,
                file_size INTEGER DEFAULT 0,
                special_folder TEXT,
                network_share TEXT,
                server_name TEXT,
                share_name TEXT,
                drive_letter TEXT,
                mft_record_number INTEGER,
                registry_path TEXT,
                parent_path TEXT,
        last_written TEXT, time_basis TEXT,
                node_slot INTEGER,
                bag_views TEXT,
                parsed_at TEXT,
                user_name TEXT
            )''')
        # Create indexes for performance
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_shellbags_file_name ON Shellbags(file_name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_shellbags_mru_position ON Shellbags(mru_position)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_shellbags_modified_date ON Shellbags(modified_date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_shellbags_mft_record ON Shellbags(mft_record_number)')
        # RunMRU table for Run dialog command history
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS RunMRU (
            command TEXT,
            mru_position INTEGER,
            access_date TEXT,
            key_last_write TEXT,
            parsed_at TEXT,
            user_name TEXT
        )''')
        # MUICache table for application name and path tracking.
        # Declared once, here. A second CREATE sat inside the collection block
        # below; IF NOT EXISTS made it a silent no-op, so the two could drift
        # apart without anything failing.
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS MUICache (
            app_path TEXT,
            app_name TEXT,
            company TEXT,
            file_extension TEXT,
            parsed_at TEXT,
            user_name TEXT
        )''')
        # Enhanced Network List table with readable information
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS Network_list (
            subkey TEXT,
            name TEXT,
            data TEXT,
            decoded TEXT,
            type TEXT,
            network_name TEXT,
            connection_date TEXT,
            gateway_mac TEXT,
            parsed_at TEXT
        )''')
        # One row per network, joining the two key trees NetworkList splits a
        # network across: Signatures\Unmanaged holds the gateway MAC and the
        # DNS suffix, Profiles holds the name, the category and the dates, and
        # ProfileGuid is what ties them together. Flattened into Network_list
        # alone they land on different rows and never meet.
        #
        # is_hidden is gone. It was derived from NameType == 6, which is a
        # WIRED network - nothing to do with hiding - and a verdict column
        # where the registry only offers a fact. name_type_label replaces it
        # with what the value actually says.
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS NetworkProfiles (
            profile_guid TEXT,
            profile_name TEXT,
            description TEXT,
            signature TEXT,
            first_network TEXT,
            gateway_mac TEXT,
            dns_suffix TEXT,
            category INTEGER,
            category_label TEXT,
            name_type INTEGER,
            name_type_label TEXT,
            managed INTEGER,
            managed_label TEXT,
            source INTEGER,
            date_created TEXT,
            date_last_connected TEXT,
            key_path TEXT,
            last_written TEXT,
            time_basis TEXT,
            parsed_at TEXT
        )''')
        # Existing case databases predate the decoded columns. They are ALTERed
        # into shape, never rebuilt - a case that has already been parsed is
        # evidence, and a re-parse must add to it without discarding anything.
        apply_decoded_columns(cursor)
        # Enhanced OpenSaveMRU table with readable information
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS OpenSaveMRU (
            subkey TEXT,
            name TEXT,
            type TEXT,
            file_path TEXT,
            file_name TEXT,
            extension TEXT,
            drive_letter TEXT,
            access_date TEXT,
            key_last_write TEXT,
            row_data TEXT,
            parsed_at TEXT,
            user_name TEXT
        )''')
        # Enhanced LastSaveMRU table with readable information
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS LastSaveMRU (
            mru_number TEXT,
            type TEXT,
            application TEXT,
            folder_path TEXT,
            folder_name TEXT,
            drive_letter TEXT,
            access_date TEXT,
            key_last_write TEXT,
            row_data TEXT,
            parsed_at TEXT,
            user_name TEXT
        )''')
        # User Profiles table for user account information from ProfileList
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS UserProfiles (
            user_sid TEXT PRIMARY KEY,
            username TEXT,
            profile_path TEXT,
            profile_image_path TEXT,
            profile_loaded INTEGER,
            parsed_at TEXT
        )''')
        # Insert data into the respective tables
        for table_name, (hive, key) in paths.items():
            output = reg_Claw_live(hive, key)
            db_table_name = table_name_mapping.get(table_name, table_name)
            for name, (data, value_type) in output.items():
                try:
                    # Check if entry exists for tables without primary keys
                    if db_table_name in ['machine_run', 'machine_run_once', 'user_run', 'user_run_once', 'DAM', 'BAM']:
                        if check_exists(cursor, db_table_name, ['name', 'row_data', 'type'], (name, str(data), value_type)):
                            logging.info(f"Skipping duplicate entry in {db_table_name}: {name}")
                            continue
                    cursor.execute(f'INSERT OR IGNORE INTO {db_table_name} (name, row_data, type) VALUES (?, ?, ?)',
                                  (name, str(data), value_type))
                    # Also insert into the AutoStartPrograms table
                    if table_name in ["machine_run", "machine_run_once", "user_run", "user_run_once"]:
                        location = {
                            "machine_run": "HKLM Run",
                            "machine_run_once": "HKLM RunOnce",
                            "user_run": "HKCU Run",
                            "user_run_once": "HKCU RunOnce"
                        }[table_name]
                        cursor.execute('INSERT OR IGNORE INTO AutoStartPrograms (location, program_name, command, key_path, record_state, parsed_at) VALUES (?, ?, ?, ?, ?, ?)',
                                      (location, name, str(data), key,
                                       LIVE_STATE,
                                       format_forensic_timestamp(get_current_utc())))
                except Exception as e:
                    logging.error(f"Error inserting into table {db_table_name} for key {key}: {e}")
        print("Auto start programs data inserted into database successfully.")
        # DAM and BAM data collection
        dam_data = reg_Claw_live(HKEY_LOCAL_MACHINE, paths['dam'][1])
        bam_data = reg_Claw_live(HKEY_LOCAL_MACHINE, paths['bam'][1])
        dam_subkeys = get_subkeys_live(HKEY_LOCAL_MACHINE, paths['dam'][1])
        bam_subkeys = get_subkeys_live(HKEY_LOCAL_MACHINE, paths['bam'][1])
        # Process DAM data
        for subkey, values in dam_subkeys.items():
            for name, (data, value_type) in values.items():
                try:
                    # Extract SID from subkey
                    sid = subkey.split('\\')[-1] if '\\' in subkey else subkey
                   
                    # Initialize default values
                    app_name = ''
                    process_path = ''
                    last_execution = ''
                    execution_count = 0
                   
                    # Use binary parser for REG_BINARY data
                    if value_type == "REG_BINARY":
                        # Convert string to bytes if needed (Windows API sometimes returns strings)
                        binary_data = data if isinstance(data, bytes) else data.encode('latin-1') if isinstance(data, str) else data
                       
                        try:
                            parsed_data = registry_binary_parser.parse_dam_entry(name, binary_data)
                            app_name = parsed_data.get('app_name', '')
                            process_path = parsed_data.get('process_path', name)
                            last_execution = parsed_data.get('last_execution', '')
                        except Exception as e:
                            logging.error(f"Error parsing DAM binary data for {subkey}/{name}: {e}")
                            # Fallback to using the name as process path
                            process_path = name
                            app_name = os.path.basename(process_path) if process_path else ''
                    else:
                        # For non-binary data, use name or string conversion
                        process_path = name if name else str(data)
                        app_name = os.path.basename(process_path) if process_path else ''
                   
                    # Check for additional metadata values
                    if 'LastAccessed' in values:
                        try:
                            filetime = int(values['LastAccessed'][0])
                            # Convert to datetime using centralized utility
                            dt = filetime_to_datetime(filetime)
                            last_execution = format_forensic_timestamp(dt)
                        except:
                            pass
                    if 'AccessCount' in values:
                        try:
                            execution_count = int(values['AccessCount'][0])
                        except:
                            pass
                    # Check if entry exists
                    # (subkey, name), matching BAM above and the offline parser.
                    if check_exists(cursor, 'DAM', ['subkey', 'name'], (subkey, name)):
                        logging.info(f"Skipping duplicate DAM entry: {subkey}/{name}")
                        continue
                    cursor.execute('INSERT OR IGNORE INTO DAM (subkey, name, row_data, type, app_name, process_path, sid, last_execution, execution_count, parsed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                                  (subkey, name, str(data), value_type, app_name, process_path, sid, last_execution, execution_count, format_forensic_timestamp(get_current_utc())))
                except Exception as e:
                    logging.error(f"Error processing DAM entry {subkey}/{name}: {e}")
        # Process BAM data
        for subkey, values in bam_subkeys.items():
            # The SID key's own last write. BAM rewrites the key as it records
            # executions, so it bounds the newest entry under it - the same
            # "key upper bound" basis every other table here uses. It was
            # declared and left empty on all 129 rows.
            bam_key_written = key_last_write_live(
                HKEY_LOCAL_MACHINE, paths['bam'][1] + chr(92) + subkey)
            for name, (data, value_type) in values.items():
                try:
                    sid = subkey.split(chr(92))[-1] if chr(92) in subkey else subkey

                    process_path = ''
                    app_name = ''
                    last_execution = ''
                    name_kind = ''
                    name_kind_raw = None
                    trailing_value = None

                    if registry_binary_parser.is_bam_metadata(name):
                        # Version and SequenceNumber are the key's own
                        # bookkeeping. They were written as programs, with
                        # app_name and process_path both set to "Version" and
                        # "SequenceNumber" - paths that exist nowhere. The row
                        # stays, because the value is really there; the program
                        # columns stay empty, because there is no program.
                        pass
                    elif value_type == 'REG_BINARY':
                        binary_data = data if isinstance(data, bytes) else data.encode('latin-1') if isinstance(data, str) else data
                        try:
                            parsed_data = registry_binary_parser.parse_bam_entry(name, binary_data)
                            process_path = parsed_data.get('process_path', name)

                            # The 24-byte blob read whole. Only the first eight
                            # were ever read. The uint32 at offset 16 says
                            # whether the value NAME is a device path or a
                            # package family name, and on the reference system
                            # it splits 53 to 60 with no exceptions - confirmed
                            # a second time straight off the live registry.
                            blob = registry_binary_parser.parse_bam_blob(binary_data)
                            last_execution = (blob['last_execution']
                                              or parsed_data.get('last_execution', ''))
                            name_kind = blob['name_kind']
                            name_kind_raw = blob['name_kind_raw']
                            trailing_value = blob['trailing_value']

                            if process_path:
                                app_name = os.path.basename(process_path)
                        except Exception as parse_error:
                            logging.error(f"Error parsing BAM binary data for {subkey}/{name}: {parse_error}")
                            process_path = name
                            app_name = os.path.basename(process_path) if process_path else ''
                    else:
                        process_path = name if name else str(data)
                        app_name = os.path.basename(process_path) if process_path else ''

                    decoded = registry_binary_parser.render_registry_value(
                        'bam', name, data, value_type)

                    # Keyed on (subkey, name) - the SID and the executable -
                    # which is what the registry stores one value for, and what
                    # the offline parser has always used.
                    #
                    # row_data was in the key, and row_data holds the execution
                    # timestamp: run the program again, re-parse, and the same
                    # executable was written a second time. On a live case BAM
                    # grew on every re-parse while an offline case never did.
                    if check_exists(cursor, 'BAM', ['subkey', 'name'], (subkey, name)):
                        logging.info(f"Skipping duplicate BAM entry: {subkey}/{name}")
                        continue
                    # execution_flags is gone. It read a value named 'Flags'
                    # that these keys do not have, so it was 0 on all 113 rows -
                    # a constant presented as a finding, while the one field
                    # that does vary was being discarded.
                    cursor.execute('INSERT OR IGNORE INTO BAM (subkey, name, row_data, decoded, type, app_name, process_path, sid, last_execution, name_kind, name_kind_raw, trailing_value, last_written, time_basis, parsed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                                  (subkey, name, str(data), decoded, value_type,
                                   app_name or None, process_path or None, sid,
                                   last_execution, name_kind, name_kind_raw,
                                   trailing_value, bam_key_written,
                                   'key upper bound' if bam_key_written else None,
                                   format_forensic_timestamp(get_current_utc())))
                except Exception as e:
                    logging.error(f"Error processing BAM entry {subkey}/{name}: {e}")
        print("DAM and BAM data inserted into database successfully.")
        # UserAssist collection - Program execution tracking
        userassist_base_path = "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\UserAssist"
       
        # Get the current user's SID once (more efficient than getting it for each entry)
        current_user_sid = get_current_user_sid()
        if not current_user_sid:
            logging.warning("Could not retrieve current user SID - will use GUID as fallback")
       
        try:
            # Enumerate UserAssist GUIDs
            with winreg.OpenKey(HKEY_CURRENT_USER, userassist_base_path) as userassist_key:
                guid_count = winreg.QueryInfoKey(userassist_key)[0]
               
                for i in range(guid_count):
                    try:
                        guid_name = winreg.EnumKey(userassist_key, i)
                        count_path = f"{userassist_base_path}\\{guid_name}\\Count"
                       
                        # Get the Count subkey values
                        try:
                            count_values = reg_Claw_live(HKEY_CURRENT_USER, count_path)
                           
                            # Process each UserAssist entry
                            for value_name, (data, value_type) in count_values.items():
                                try:
                                    # Skip non-binary values
                                    if value_type != "REG_BINARY":
                                        continue
                                   
                                    # Ensure we have bytes for parsing
                                    if not isinstance(data, bytes):
                                        logging.warning(f"UserAssist data for {value_name} is not bytes: type={type(data)}, value={data}")
                                        if isinstance(data, str):
                                            binary_data = data.encode('latin-1')
                                        else:
                                            logging.error(f"Cannot convert UserAssist data to bytes for {value_name}")
                                            continue
                                    else:
                                        binary_data = data
                                   
                                    # Debug: Log binary data info
                                    logging.debug(f"UserAssist entry {value_name}: data_length={len(binary_data)}, first_bytes={binary_data[:16].hex() if len(binary_data) >= 16 else binary_data.hex()}")
                                   
                                    # Parse UserAssist entry
                                    parsed_data = registry_binary_parser.parse_userassist_entry(value_name, binary_data)
                                   
                                    program_path = parsed_data.get('program_path', '')
                                    run_count = parsed_data.get('run_count', 0)
                                    last_execution = parsed_data.get('last_execution', '')
                                    focus_count = parsed_data.get('focus_count', 0)
                                    focus_time_ms = parsed_data.get('focus_time', 0)
                                    
                                    # focus_time is an INTEGER column, and
                                    # format_focus_time returns "2.47h" / "0.00s".
                                    # SQLite stores an unconvertible string as
                                    # TEXT, and TEXT sorts above every integer -
                                    # so ordering by focus time, or asking for the
                                    # sessions above a threshold, was meaningless.
                                    # The readable form belongs to the display
                                    # layer, which now renders it there; the
                                    # offline parser has always stored the number.
                                    focus_time_formatted = int(focus_time_ms or 0)
                                   
                                    # Use actual user SID if available, otherwise fall back to GUID
                                    user_sid = current_user_sid if current_user_sid else guid_name
                                   
                                    # Check if entry exists. Matches the enriched
                                    # "SID (MACHINE\user)" form too - the identity
                                    # pass rewrites this column, and comparing to
                                    # the bare SID stopped matching afterwards, so
                                    # every re-parse appended the whole table.
                                    if user_identity.row_exists_for_sid(
                                            cursor, 'UserAssist', ['program_path'],
                                            (program_path,), 'user_sid', user_sid):
                                        logging.info(f"Skipping duplicate UserAssist entry: {program_path}")
                                        continue
                                   
                                    # Insert into database with formatted focus time
                                    cursor.execute('''INSERT OR IGNORE INTO UserAssist
                                                   (program_path, run_count, last_execution, focus_count, focus_time, user_sid, parsed_at)
                                                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                                                 (program_path, run_count, last_execution, focus_count, focus_time_formatted,
                                                  user_sid, format_forensic_timestamp(get_current_utc())))
                                    
                                    logging.info(f"Inserted UserAssist: {program_path} | count={run_count}, focus={focus_count}, time={focus_time_formatted} ({focus_time_ms}ms), exec={last_execution}")
                                   
                                except Exception as e:
                                    logging.error(f"Error parsing UserAssist entry {value_name} in {guid_name}: {e}")
                                    import traceback
                                    logging.error(traceback.format_exc())
                                    continue
                       
                        except Exception as e:
                            logging.error(f"Error accessing UserAssist Count key for {guid_name}: {e}")
                            continue
                   
                    except Exception as e:
                        logging.error(f"Error enumerating UserAssist GUID at index {i}: {e}")
                        continue
           
            print("UserAssist data inserted into database successfully.")
       
        except Exception as e:
            logging.error(f"Error accessing UserAssist base key: {e}")
            print(f"Warning: Could not access UserAssist data: {e}")
        # Shellbags collection - Folder access history
        shellbags_paths = [
            "Software\\Microsoft\\Windows\\Shell\\BagMRU",
            "Software\\Microsoft\\Windows\\ShellNoRoam\\BagMRU",
            "Software\\Classes\\Local Settings\\Software\\Microsoft\\Windows\\Shell\\BagMRU"
        ]
       
        # Explorer files a window's view settings under Shell; a common File
        # Open/Save dialog files its own under ComDlg. Listed in that order
        # rather than alphabetically, because that is the order a reader cares
        # about, and fixed rather than arbitrary so a re-parse is stable.
        _VIEW_ORDER = {"Shell": 0, "ComDlg": 1}

        def _bag_view(hive_key, bags_path, folder_key):
            """Which kind of shell view wrote this folder's bag, if any.

            A BagMRU key carries a NodeSlot DWORD naming a subkey of the Bags
            tree beside it, and that subkey holds the view settings. This is
            the only place on disk that distinguishes a bag written by an
            Explorer window from one written by a file dialog inside some
            other program.

            The slot is read from the folder's OWN key. An item is value N of
            key P and the folder it names is P\\N, so reading the slot off P
            would give every row its parent's view - a wrong answer that looks
            entirely plausible.

            Returns (node_slot, views). `views` is the subkeys that are
            actually there, joined - no interpretation. Either may be None: on
            the reference system 58 of 839 keys carry no NodeSlot at all, and
            an empty column is the honest answer for those.
            """
            try:
                with winreg.OpenKey(hive_key, folder_key) as key:
                    slot = winreg.QueryValueEx(key, "NodeSlot")[0]
            except OSError:
                return None, None
            if not isinstance(slot, int):
                return None, None
            try:
                with winreg.OpenKey(hive_key,
                                    bags_path + BS_SEP + str(slot)) as bag:
                    n_sub = winreg.QueryInfoKey(bag)[0]
                    views = [winreg.EnumKey(bag, i) for i in range(n_sub)]
            except OSError:
                return slot, None
            views.sort(key=lambda v: (_VIEW_ORDER.get(v, 2), v))
            return slot, (",".join(views) or None)

        def _shellbag_name(binary_data):
            """Decoded folder name for one BagMRU value, or '' if it will not parse."""
            try:
                return registry_binary_parser.parse_shellbag_entry(
                    binary_data).get('file_name', '') or ''
            except Exception:
                return ''

        def enumerate_shellbags_recursive(hive_key, base_path, current_path="", depth=0,
                                          max_depth=20, parent_readable=""):
            """
            Recursively enumerate Shellbags keys to capture nested folder structures.

            Args:
                hive_key: Registry hive (HKEY_CURRENT_USER)
                base_path: Base registry path for Shellbags
                current_path: Current subkey path (for recursion)
                depth: Current recursion depth
                max_depth: Maximum recursion depth to prevent infinite loops
                parent_readable: Decoded folder path of the key being descended into.
                    BagMRU nests by index - subkey N holds the children of value N in
                    the same key - so the readable parent is built on the way down,
                    while registry_path only ever records the numeric chain.

            Returns:
                List of tuples: (registry_path, value_name, binary_data, mru_position,
                                 parent_path)
            """
            if depth >= max_depth:
                logging.warning(f"Maximum recursion depth reached for Shellbags at {base_path}\\{current_path}")
                return []
           
            entries = []
            full_path = f"{base_path}\\{current_path}" if current_path else base_path
            # The Bags tree is the sibling of BagMRU, per hive - Shell,
            # ShellNoRoam and the UsrClass tree each have their own. Derived
            # from the base path so all three resolve without a constant.
            bags_path = base_path.rsplit(BS_SEP, 1)[0] + BS_SEP + "Bags"
           
            try:
                # Get values from current key
                values = reg_Claw_live(hive_key, full_path)
               
                # Parse MRUListEx to get access order
                mru_order = []
                if 'MRUListEx' in values:
                    mrulistex_data, mrulistex_type = values['MRUListEx']
                    if isinstance(mrulistex_data, bytes):
                        try:
                            mru_order = registry_binary_parser.parse_mru_list_ex(mrulistex_data)
                            logging.debug(f"Parsed Shellbags MRUListEx for {full_path}: {mru_order}")
                        except Exception as e:
                            logging.error(f"Error parsing Shellbags MRUListEx for {full_path}: {e}")
               
                # Process each value (except MRUListEx)
                for value_name, (data, value_type) in values.items():
                    if value_name.lower() == 'mrulistex':
                        continue
                   
                    # Determine MRU position
                    mru_position = -1
                    try:
                        value_index = int(value_name)
                        if mru_order and value_index in mru_order:
                            mru_position = mru_order.index(value_index)
                    except (ValueError, TypeError):
                        pass
                   
                    # Only process binary data (Shell Item IDs)
                    if value_type == "REG_BINARY" and isinstance(data, bytes):
                        node_slot, bag_views = _bag_view(
                            hive_key, bags_path,
                            full_path + BS_SEP + value_name)
                        entries.append((full_path, value_name, data, mru_position,
                                        parent_readable, node_slot, bag_views))

                # Recursively enumerate subkeys
                try:
                    with winreg.OpenKey(hive_key, full_path) as key:
                        subkey_count = winreg.QueryInfoKey(key)[0]

                        for i in range(subkey_count):
                            try:
                                subkey_name = winreg.EnumKey(key, i)
                                # Skip MRUListEx subkey if it exists
                                if subkey_name.lower() == 'mrulistex':
                                    continue

                                # The folder this subkey descends into is the value
                                # of the same name in the current key.
                                _own = ''
                                _v = values.get(subkey_name)
                                if _v and isinstance(_v[0], bytes):
                                    _own = _shellbag_name(_v[0])
                                child_readable = (f"{parent_readable}\\{_own}"
                                                  if parent_readable and _own
                                                  else (_own or parent_readable))

                                # Recursively process subkey
                                subkey_path = f"{current_path}\\{subkey_name}" if current_path else subkey_name
                                sub_entries = enumerate_shellbags_recursive(
                                    hive_key, base_path, subkey_path, depth + 1,
                                    max_depth, child_readable)
                                entries.extend(sub_entries)
                            except Exception as e:
                                logging.error(f"Error enumerating Shellbags subkey {i} in {full_path}: {e}")
                                continue
                except Exception as e:
                    logging.error(f"Error accessing Shellbags subkeys for {full_path}: {e}")
           
            except Exception as e:
                logging.error(f"Error accessing Shellbags key {full_path}: {e}")

            return entries

        def store_shellbag_entries(entries, user_name=None):
            """Decode and write BagMRU entries. Returns the number of rows written.

            One decode path for every user. The other-user pass used to walk the
            same tuples with .get(), which raises AttributeError on a tuple - so
            it wrote nothing at all, quietly, for every account but the one
            running Crow-Eye.
            """
            written = 0
            for (registry_path, value_name, binary_data, mru_position,
                 parent_path, node_slot, bag_views) in entries:
                try:
                    # Parse Shellbag entry with enhanced metadata
                    parsed_data = registry_binary_parser.parse_shellbag_entry(binary_data)

                    file_name = parsed_data.get('file_name', '')
                    short_name = parsed_data.get('short_name', '')
                    shell_item_type = parsed_data.get('shell_item_type', 'unknown')

                    # Enhanced metadata
                    created_date = parsed_data.get('created_date', '')
                    modified_date = parsed_data.get('modified_date', '')
                    accessed_date = parsed_data.get('accessed_date', '')
                    attributes = parsed_data.get('attributes', '')
                    file_size = parsed_data.get('file_size', 0)
                    special_folder = parsed_data.get('special_folder', '')
                    network_share = parsed_data.get('network_share', '')
                    server_name = parsed_data.get('server_name', '')
                    share_name = parsed_data.get('share_name', '')
                    drive_letter = parsed_data.get('drive_letter', '')
                    mft_record_number = parsed_data.get('mft_record_number', 0)

                    # Skip empty entries
                    if not file_name:
                        logging.debug(f"Skipping empty Shellbags entry at {registry_path}/{value_name}")
                        continue

                    # Keyed by user too: the same folder opened by two accounts is
                    # two findings. The table carries no constraint, so this check
                    # is the only thing keeping a re-parse from duplicating it.
                    if check_exists(cursor, 'Shellbags',
                                    ['file_name', 'registry_path', 'user_name'],
                                    (file_name, registry_path, user_name)):
                        backfill_shellbag_view(cursor, file_name, registry_path,
                                               user_name, node_slot, bag_views)
                        logging.debug(f"Skipping duplicate Shellbags entry: {file_name}")
                        continue

                    # Note: mru_position is TEXT to support the "Unknown" value
                    cursor.execute('''INSERT INTO Shellbags
                                   (file_name, short_name, shell_item_type, mru_position,
                                    created_date, modified_date, accessed_date, attributes,
                                    file_size, special_folder, network_share, server_name, share_name,
                                    drive_letter, mft_record_number, registry_path, parent_path,
                                    node_slot, bag_views, parsed_at, user_name)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                                 (file_name, short_name, shell_item_type, mru_position,
                                  created_date, modified_date, accessed_date, attributes,
                                  file_size, special_folder, network_share, server_name, share_name,
                                  drive_letter, mft_record_number, registry_path, parent_path,
                                  node_slot, bag_views,
                                  format_forensic_timestamp(get_current_utc()), user_name))

                    written += 1
                    logging.debug(f"Shellbag {value_name} MRU position: {mru_position}")

                except Exception as e:
                    logging.error(f"Error parsing Shellbags entry {registry_path}/{value_name}: {e}")
                    import traceback
                    logging.debug(traceback.format_exc())
                    continue
            return written

        try:
            shellbags_count = 0
           
            # Enumerate Shellbags from all registry paths
            for shellbags_path in shellbags_paths:
                try:
                    logging.info(f"Enumerating Shellbags from {shellbags_path}")
                   
                    # Recursively enumerate all Shellbags entries
                    entries = enumerate_shellbags_recursive(HKEY_CURRENT_USER, shellbags_path)
                   
                    # Process each entry
                    shellbags_count += store_shellbag_entries(entries, _live_user)
               
                except Exception as e:
                    logging.error(f"Error accessing Shellbags path {shellbags_path}: {e}")
                    continue
           
            print(f"Shellbags data inserted into database successfully. Total entries: {shellbags_count}")
       
        except Exception as e:
            logging.error(f"Error during Shellbags collection: {e}")
            print(f"Warning: Could not complete Shellbags collection: {e}")
        # RunMRU collection - Run dialog command history
        runmru_path = "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\RunMRU"
       
        try:
            # Read RunMRU values
            runmru_values = reg_Claw_live(HKEY_CURRENT_USER, runmru_path)

            # The registry records no per-entry time for an MRU list; only the
            # key carries a last-write. Storing it against the newest entry
            # would be an inference presented as evidence, so access_date stays
            # empty and the key's own timestamp is recorded as what it is - a
            # property of the key, true for every row read from it.
            _rm_lastwrite = key_last_write_live(HKEY_CURRENT_USER, runmru_path)
           
            # Extract MRUList to determine command execution order
            mru_list = ""
            if 'MRUList' in runmru_values:
                mru_list_data, mru_list_type = runmru_values['MRUList']
                if mru_list_type == "REG_SZ":
                    mru_list = str(mru_list_data).strip()
                    logging.info(f"RunMRU MRUList: {mru_list}")
           
            runmru_count = 0
           
            # Process each RunMRU entry
            for value_name, (data, value_type) in runmru_values.items():
                try:
                    # Skip MRUList itself
                    if value_name.lower() == 'mrulist':
                        continue
                   
                    # Only process REG_SZ values (command strings)
                    if value_type != "REG_SZ":
                        continue
                   
                    # Convert data to string
                    command_string = str(data).strip()
                   
                    # Skip empty commands
                    if not command_string:
                        logging.debug(f"Skipping empty RunMRU entry: {value_name}")
                        continue
                   
                    # Parse RunMRU entry
                    parsed_data = registry_binary_parser.parse_runmru_entry(value_name, command_string, mru_list)
                   
                    command = parsed_data.get('command', '')
                    mru_position = parsed_data.get('mru_position', -1)
                    access_date = parsed_data.get('timestamp', None)
                   
                    # Skip if no command extracted
                    if not command:
                        logging.debug(f"Skipping RunMRU entry with no command: {value_name}")
                        continue
                   
                    # Check if entry exists
                    if check_exists(cursor, 'RunMRU', ['command', 'mru_position', 'user_name'], (command, mru_position, _live_user)):
                        logging.info(f"Skipping duplicate RunMRU entry: {command}")
                        continue
                   
                    # Insert into database
                    cursor.execute('''INSERT INTO RunMRU
                                   (command, mru_position, access_date, key_last_write,
                                    parsed_at, user_name)
                                   VALUES (?, ?, ?, ?, ?, ?)''',
                                 (command, mru_position, access_date, _rm_lastwrite,
                                  format_forensic_timestamp(get_current_utc()), _live_user))
                   
                    runmru_count += 1
                   
                except Exception as e:
                    logging.error(f"Error parsing RunMRU entry {value_name}: {e}")
                    continue
           
            print(f"RunMRU data inserted into database successfully. Total entries: {runmru_count}")
       
        except Exception as e:
            logging.error(f"Error accessing RunMRU registry key: {e}")
            print(f"Warning: Could not access RunMRU data: {e}")
        # MUICache collection - Application name and path tracking
        muicache_paths = [
            "Software\\Classes\\Local Settings\\Software\\Microsoft\\Windows\\Shell\\MuiCache",
            "Software\\Microsoft\\Windows\\ShellNoRoam\\MUICache"
        ]
       
        muicache_count = 0
       
        # Windows stores one value per PROPERTY of an executable
        # ("<path>.FriendlyAppName", "<path>.ApplicationCompany"), so the values
        # are pivoted back into one row per executable here. Written straight
        # through, the same program appeared once per property with the property
        # name left on its path.
        muicache_apps = {}
        for muicache_path in muicache_paths:
            try:
                # Try to read MUICache values from this path
                muicache_values = reg_Claw_live(HKEY_CURRENT_USER, muicache_path)

                # Process each MUICache entry
                for value_name, (data, value_type) in muicache_values.items():
                    try:
                        # Only process REG_SZ values (application display names)
                        if value_type != "REG_SZ":
                            continue

                        # Convert data to string
                        app_display_name = str(data).strip()

                        # Skip empty values
                        if not value_name or not app_display_name:
                            logging.debug(f"Skipping empty MUICache entry: {value_name}")
                            continue

                        # Parse MUICache entry
                        parsed_data = registry_binary_parser.parse_muicache_entry(value_name, app_display_name)

                        app_path = parsed_data.get('app_path', '')
                        file_extension = parsed_data.get('file_extension', '')
                        prop = (parsed_data.get('muicache_property') or '').lower()

                        # Skip if no path extracted
                        if not app_path:
                            logging.debug(f"Skipping MUICache entry with no path: {value_name}")
                            continue

                        entry = muicache_apps.setdefault(
                            app_path, {'file_extension': file_extension,
                                       'app_name': '', 'company': ''})
                        if prop == 'applicationcompany':
                            entry['company'] = app_display_name
                        elif prop in ('friendlyappname', 'applicationname'):
                            entry['app_name'] = app_display_name
                        elif not entry['app_name'] and not prop:
                            # No property suffix: the older ShellNoRoam form,
                            # where the value data is the display name itself.
                            entry['app_name'] = app_display_name

                    except Exception as e:
                        logging.error(f"Error parsing MUICache entry {value_name}: {e}")
                        continue

            except Exception as e:
                logging.debug(f"MUICache path not accessible: {muicache_path} - {e}")
                continue

        for app_path, entry in muicache_apps.items():
            try:
                # Keyed by user as well as path. On app_path alone, a program
                # used by two accounts is stored once and the second account's
                # use disappears.
                if check_exists(cursor, 'MUICache', ['app_path', 'user_name'],
                                (app_path, _live_user)):
                    logging.info(f"Skipping duplicate MUICache entry: {app_path}")
                    continue
                cursor.execute('''INSERT INTO MUICache
                               (app_path, app_name, company, file_extension, parsed_at, user_name)
                               VALUES (?, ?, ?, ?, ?, ?)''',
                             (app_path, entry['app_name'], entry['company'],
                              entry['file_extension'],
                              format_forensic_timestamp(get_current_utc()), _live_user))
                muicache_count += 1
            except Exception as e:
                logging.error(f"Error inserting MUICache entry {app_path}: {e}")
                continue
       
        print(f"MUICache data inserted into database successfully. Total entries: {muicache_count}")
        # WordWheelQuery collection - Windows Explorer search history
        wordwheelquery_count = 0
        wordwheelquery_path = "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\WordWheelQuery"
       
        try:
            wordwheelquery_data = reg_Claw_live(HKEY_CURRENT_USER, wordwheelquery_path)

            # Same as RunMRU: the key's last-write is the only timestamp that
            # exists, and it belongs to the key rather than to any one search.
            _ww_lastwrite = key_last_write_live(HKEY_CURRENT_USER, wordwheelquery_path)
           
            # Extract MRUListEx for proper ordering
            mru_list_ex_data = None
            if 'MRUListEx' in wordwheelquery_data:
                mru_list_ex_data = wordwheelquery_data['MRUListEx'][0]
                if not isinstance(mru_list_ex_data, bytes):
                    # Convert to bytes if needed
                    mru_list_ex_data = mru_list_ex_data.encode('latin-1') if isinstance(mru_list_ex_data, str) else None
           
            # Process each WordWheelQuery entry
            for value_name, (data, value_type) in wordwheelquery_data.items():
                try:
                    # Skip MRUListEx - it's used for ordering, not a search term
                    if value_name == 'MRUListEx':
                        continue
                   
                    # Skip non-binary values (we expect REG_BINARY for search terms)
                    if value_type != "REG_BINARY":
                        continue
                   
                    # Convert string to bytes if needed
                    binary_data = data if isinstance(data, bytes) else data.encode('latin-1') if isinstance(data, str) else data
                   
                    # Parse WordWheelQuery entry using the enhanced parser
                    parsed_data = registry_binary_parser.parse_wordwheelquery_entry(
                        value_name,
                        binary_data,
                        mru_list_ex_data
                    )
                   
                    search_term = parsed_data.get('search_term', '')
                    search_type = parsed_data.get('search_type', 'General')
                    mru_position = parsed_data.get('mru_position', -1)
                    access_date = parsed_data.get('timestamp', None)
                   
                    # Skip empty search terms
                    if not search_term:
                        continue
                   
                    # Check if entry exists
                    if check_exists(cursor, 'WordWheelQuery', ['search_term', 'search_type'], (search_term, search_type)):
                        logging.info(f"Skipping duplicate WordWheelQuery entry: {search_term}")
                        continue
                   
                    # Insert into WordWheelQuery table with error handling
                    try:
                        cursor.execute('''INSERT INTO WordWheelQuery
                                       (search_term, search_type, mru_position, access_date,
                                        key_last_write, parsed_at, user_name)
                                       VALUES (?, ?, ?, ?, ?, ?, ?)''',
                                     (search_term, search_type, mru_position, access_date,
                                      _ww_lastwrite,
                                      format_forensic_timestamp(get_current_utc()), _live_user))
                        wordwheelquery_count += 1
                    except Exception as db_error:
                        logging.error(f"Error inserting WordWheelQuery entry into database: {db_error}")
                        continue
                   
                except Exception as e:
                    logging.error(f"Error parsing WordWheelQuery entry {value_name}: {e}")
                    continue
       
        except Exception as e:
            logging.error(f"Error accessing WordWheelQuery registry key: {e}")
       
        print(f"WordWheelQuery data inserted into database successfully. Total entries: {wordwheelquery_count}")
        
        # Network List Keys - Enhanced version
        # Extract from ALL three paths: Profiles, Signatures\Unmanaged, Signatures\Managed
        # NetworkList splits one network across two key trees, joined by
        # ProfileGuid:
        #
        #   Signatures\Unmanaged\<signature>  DefaultGatewayMac, DnsSuffix,
        #                                     FirstNetwork, ProfileGuid
        #   Profiles\<guid>                   ProfileName, Category, NameType,
        #                                     DateCreated, DateLastConnected
        #
        # Flattened into one row-per-value table they never meet: each network
        # appeared twice, once with a gateway MAC and no dates and once with
        # dates and no MAC. The join that was attempted here read the Profiles
        # key back through the live API, so it could not work offline at all.
        #
        # Both trees are collected first and joined from the values already
        # read, so live and offline produce the same rows.
        NETLIST_BASE = ("SOFTWARE" + chr(92) + "Microsoft" + chr(92)
                        + "Windows NT" + chr(92) + "CurrentVersion" + chr(92)
                        + "NetworkList")
        network_list_paths = [
            (NETLIST_BASE + chr(92) + "Profiles", "profile"),
            (NETLIST_BASE + chr(92) + "Signatures" + chr(92) + "Unmanaged",
             "signature"),
            (NETLIST_BASE + chr(92) + "Signatures" + chr(92) + "Managed",
             "signature"),
        ]

        netlist_profiles = {}      # guid -> values
        netlist_signatures = []    # (signature, values)

        for Netlist_reg_key, kind in network_list_paths:
            try:
                logging.debug(f"Checking Network Lists path: {Netlist_reg_key}")
                Networklosts_subkeys = get_subkeys_live(HKEY_LOCAL_MACHINE, Netlist_reg_key)
                if not Networklosts_subkeys:
                    continue

                for subkey, values in Networklosts_subkeys.items():
                    if kind == "profile":
                        netlist_profiles[str(subkey).strip().lower()] = (
                            subkey, values, Netlist_reg_key)
                    else:
                        netlist_signatures.append(
                            (subkey, values, Netlist_reg_key))

                    # The raw row-per-value table. network_name, the connection
                    # date and the gateway MAC are read up front so every row
                    # of a key carries them rather than only the rows written
                    # after that value happened to be reached.
                    network_name = ""
                    connection_date = ""
                    gateway_mac = ""
                    for _n, (_d, _t) in values.items():
                        _low = _n.lower()
                        if _low == 'datelastconnected' and isinstance(_d, bytes):
                            connection_date = (
                                registry_binary_parser.parse_systemtime(_d)
                                or connection_date)
                        elif _low == 'defaultgatewaymac' and isinstance(_d, bytes) and len(_d) >= 6:
                            gateway_mac = registry_binary_parser.format_mac_address(_d)
                        elif _low == 'firstnetwork':
                            network_name = str(_d)
                        elif _low == 'profilename' and not network_name:
                            network_name = str(_d)

                    for name, (data, value_type) in values.items():
                        # Each value decodes its own way: DefaultGatewayMac is
                        # six bytes of MAC, DateCreated is a SYSTEMTIME,
                        # Category and NameType are enumerations. str(data)
                        # made all three unreadable.
                        decoded = registry_binary_parser.render_registry_value(
                            'networklist', name, data, value_type)
                        if check_exists(cursor, 'Network_list', ['subkey', 'name', 'data', 'type'], (str(subkey), name, str(data), value_type)):
                            logging.debug(f"Skipping duplicate Network_list entry: {subkey}/{name}")
                            continue
                        cursor.execute(
                            'INSERT OR IGNORE INTO Network_list '
                            '(subkey, name, data, decoded, type, network_name, '
                            'connection_date, gateway_mac, parsed_at) '
                            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                            (str(subkey), name, str(data), decoded, value_type,
                             network_name, connection_date, gateway_mac,
                             format_forensic_timestamp(get_current_utc())))

                logging.debug(f"Network list data from {Netlist_reg_key} inserted successfully")
            except Exception as e:
                logging.debug(f"Network Lists path unavailable: {Netlist_reg_key} - {e}")

        # --- one row per network -------------------------------------------
        def _nl_value(values, want):
            for _n, (_d, _t) in values.items():
                if _n.lower() == want:
                    return _d
            return None

        def _nl_int(values, want):
            raw = _nl_value(values, want)
            try:
                return int(raw)
            except (TypeError, ValueError):
                return None

        try:
            seen_profiles = set()
            rows = []
            for signature, sig_values, sig_path in netlist_signatures:
                guid = _nl_value(sig_values, 'profileguid')
                key = str(guid).strip().lower() if guid else ""
                prof = netlist_profiles.get(key)
                prof_values = prof[1] if prof else {}
                if key:
                    seen_profiles.add(key)
                # Both keys, each with its own full path. Building one
                # path by concatenating a name that can be empty is how the
                # first version of this ended up opening the PARENT key: a
                # trailing separator is tolerated, so every row got the
                # Profiles key's write time instead of its own.
                rows.append((guid, signature, sig_values, prof_values,
                             (prof[2] + chr(92) + str(prof[0])) if prof else "",
                             sig_path + chr(92) + str(signature)))

            # A profile with no signature is still a network the machine
            # joined. Dropping it would mean the summary quietly held fewer
            # networks than the registry does.
            for key, (guid, prof_values, prof_path) in netlist_profiles.items():
                if key not in seen_profiles:
                    rows.append((guid, "", {}, prof_values,
                                 prof_path + chr(92) + str(guid), ""))

            for (guid, signature, sig_values, prof_values, profile_key,
                 signature_key) in rows:
                mac_raw = _nl_value(sig_values, 'defaultgatewaymac')
                category = _nl_int(prof_values, 'category')
                name_type = _nl_int(prof_values, 'nametype')
                managed = _nl_int(prof_values, 'managed')
                created = _nl_value(prof_values, 'datecreated')
                last_conn = _nl_value(prof_values, 'datelastconnected')
                profile_name = _nl_value(prof_values, 'profilename')
                description = (_nl_value(prof_values, 'description')
                               or _nl_value(sig_values, 'description'))
                # The profile key carries the dates, so its write time is
                # the one that bounds this row. Falls back to the signature
                # key for a signature with no profile behind it.
                key_path = profile_key or signature_key
                written = (key_last_write_live(HKEY_LOCAL_MACHINE, profile_key)
                           if profile_key else "")
                if not written and signature_key:
                    written = key_last_write_live(HKEY_LOCAL_MACHINE,
                                                  signature_key)
                if check_exists(cursor, 'NetworkProfiles',
                                ['profile_guid', 'signature'],
                                (str(guid or ""), str(signature or ""))):
                    continue
                cursor.execute(
                    'INSERT INTO NetworkProfiles (profile_guid, profile_name, '
                    'description, signature, first_network, gateway_mac, '
                    'dns_suffix, category, category_label, name_type, '
                    'name_type_label, managed, managed_label, source, '
                    'date_created, date_last_connected, key_path, '
                    'last_written, time_basis, parsed_at) VALUES '
                    '(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (str(guid or ""),
                     str(profile_name) if profile_name is not None else None,
                     str(description) if description is not None else None,
                     str(signature or ""),
                     str(_nl_value(sig_values, 'firstnetwork') or "") or None,
                     (registry_binary_parser.format_mac_address(mac_raw)
                      if isinstance(mac_raw, bytes) and len(mac_raw) >= 6 else None),
                     # "<none>" is what Windows itself writes when a network
                     # has no DNS suffix. It is carried through as found - it
                     # is the registry's answer, not a missing value.
                     str(_nl_value(sig_values, 'dnssuffix'))
                     if _nl_value(sig_values, 'dnssuffix') is not None else None,
                     category,
                     registry_binary_parser.network_category_label(category)
                     if category is not None else None,
                     name_type,
                     registry_binary_parser.network_name_type_label(name_type)
                     if name_type is not None else None,
                     managed,
                     registry_binary_parser.network_managed_label(managed)
                     if managed is not None else None,
                     _nl_int(sig_values, 'source'),
                     registry_binary_parser.parse_systemtime(created)
                     if isinstance(created, bytes) else None,
                     registry_binary_parser.parse_systemtime(last_conn)
                     if isinstance(last_conn, bytes) else None,
                     key_path, written,
                     'key upper bound' if written else None,
                     format_forensic_timestamp(get_current_utc())))
        except Exception as exc:
            logging.error("NetworkProfiles could not be built: %s", exc)

        print("Network list key data inserted into database successfully with enhanced information.")
        # Windows Last update - Enhanced version
        last_update_path = "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\WindowsUpdate"
        last_update_regkey = reg_Claw_live(HKEY_LOCAL_MACHINE, last_update_path)
        last_update_subkey = get_subkeys_live(HKEY_LOCAL_MACHINE, last_update_path)
        auto_update_path = "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\WindowsUpdate\\Auto Update"
        auto_update_regkey = reg_Claw_live(HKEY_LOCAL_MACHINE, auto_update_path)
        # Extract Windows Update information
        last_check = ""
        last_install = ""
        au_options = 0
        scheduled_day = 0
        scheduled_time = 0
        # Check main WindowsUpdate key
        for name, (data, _) in last_update_regkey.items():
            if name.lower() == "lastchecktime":
                last_check = str(data)
            elif name.lower() == "susclientidvalidation" and isinstance(data, bytes):
                # Parse SusClientIdValidation binary data
                try:
                    parsed_val = registry_binary_parser.parse_susclientid_validation(data)
                    # Guarded like the sibling insert below. OR IGNORE alone does
                    # nothing here - Windows_lastupdate carries no UNIQUE
                    # constraint - so this row was appended on every re-parse.
                    if parsed_val and not check_exists(
                            cursor, 'Windows_lastupdate', ['name'],
                            ("SusClientIdValidation_Parsed",)):
                        cursor.execute('INSERT INTO Windows_lastupdate (name, row_data, type) VALUES (?, ?, ?)',
                                      ("SusClientIdValidation_Parsed", parsed_val, "REG_SZ"))
                except:
                    pass

            if check_exists(cursor, 'Windows_lastupdate', ['name', 'row_data', 'type'], (name, str(data), _)):
                logging.info(f"Skipping duplicate Windows_lastupdate entry: {name}")
                continue
            cursor.execute('INSERT OR IGNORE INTO Windows_lastupdate (name, row_data, type) VALUES (?, ?, ?)',
                          (name, str(data), _))
        # Check Auto Update key
        for name, (data, _) in auto_update_regkey.items():
            if name.lower() == "lastinstalltime":
                last_install = str(data)
            elif name.lower() == "auoptions":
                try:
                    au_options = int(data)
                except:
                    au_options = 0
            elif name.lower() == "scheduledinstallday":
                try:
                    scheduled_day = int(data)
                except:
                    scheduled_day = 0
            elif name.lower() == "scheduledinstalltime":
                try:
                    scheduled_time = int(data)
                except:
                    scheduled_time = 0
        # Insert into the enhanced table
        if not check_exists(cursor, 'WindowsUpdateInfo', ['last_check_time', 'last_install_time'], (last_check, last_install)):
            cursor.execute('''
            INSERT INTO WindowsUpdateInfo
            (last_check_time, last_install_time, au_options, scheduled_install_day, scheduled_install_time, parsed_at)
            VALUES (?, ?, ?, ?, ?, ?)''',
            (last_check, last_install, au_options, scheduled_day, scheduled_time, format_forensic_timestamp(get_current_utc())))
        else:
            logging.info("Skipping duplicate WindowsUpdateInfo entry")
        # Insert subkeys data
        for subkey, values in last_update_subkey.items():
            for name, (data, value_type) in values.items():
                if check_exists(cursor, 'Windows_lastupdate_subkeys', ['subkey', 'name', 'row_data', 'type'], (str(subkey), name, str(data), value_type)):
                    logging.info(f"Skipping duplicate Windows_lastupdate_subkeys entry: {subkey}/{name}")
                    continue
                cursor.execute('INSERT OR IGNORE INTO Windows_lastupdate_subkeys '
                               '(subkey, name, row_data, row_decoded, type) '
                               'VALUES (?, ?, ?, ?, ?)',
                              (str(subkey), name, str(data),
                               _row_decoded('Windows_lastupdate_subkeys', name,
                                            data, value_type),
                               value_type))
        print("Windows last update key data inserted into database successfully.")
        # Computer Name - Enhanced version
        computerName_reg_path = "SYSTEM\\CurrentControlSet\\Control\\ComputerName\\ComputerName"
        ComputerName_reg_key = reg_Claw_live(HKEY_LOCAL_MACHINE, computerName_reg_path)
        # Get additional system information
        system_info_path = "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion"
        system_info = reg_Claw_live(HKEY_LOCAL_MACHINE, system_info_path)
        # Extract computer name
        computer_name = ""
        registered_owner = ""
        registered_org = ""
        product_name = ""
        product_id = ""
        install_date = ""
        for name, (data, _) in ComputerName_reg_key.items():
            # winreg reports a key's default value as an empty name. "(Default)"
            # is what this codebase calls it - see offline_RegClaw._default_name,
            # which exists for exactly this - so an unnamed row does not appear
            # under two spellings depending on how the case was acquired.
            if not name:
                name = "(Default)"
            if name.lower() == "computername":
                computer_name = str(data)
                logging.debug(f"Extracted ComputerName: {computer_name}")
            if check_exists(cursor, 'computer_Name', ['name', 'row_data', 'type'], (name, str(data), _)):
                logging.info(f"Skipping duplicate computer_Name entry: {name}")
                continue
            cursor.execute('INSERT OR IGNORE INTO computer_Name (name, row_data, type) VALUES (?, ?, ?)',
                          (name, str(data), _))
        # Extract system info
        for name, (data, _) in system_info.items():
            if name.lower() == "registeredowner":
                registered_owner = str(data)
                logging.debug(f"Extracted RegisteredOwner: {registered_owner}")
            elif name.lower() == "registeredorganization":
                registered_org = str(data)
                logging.debug(f"Extracted RegisteredOrganization: {registered_org}")
            elif name.lower() == "productname":
                product_name = str(data)
                logging.debug(f"Extracted ProductName: {product_name}")
            elif name.lower() == "productid":
                product_id = str(data)
                logging.debug(f"Extracted ProductId: {product_id}")
            elif name.lower() == "installdate":
                try:
                    # Convert Windows timestamp to readable date
                    install_date = format_forensic_timestamp(datetime.datetime.fromtimestamp(int(data), tz=datetime.timezone.utc))
                    logging.debug(f"Extracted InstallDate: {install_date}")
                except:
                    install_date = str(data)
                    logging.debug(f"Extracted InstallDate (raw): {install_date}")
        # Insert into the enhanced table
        if not check_exists(cursor, 'ComputerNameInfo', ['computer_name', 'registered_owner'], (computer_name, registered_owner)):
            cursor.execute('''
            INSERT INTO ComputerNameInfo
            (computer_name, registered_owner, registered_organization, product_id, installation_date, parsed_at)
            VALUES (?, ?, ?, ?, ?, ?)''',
            (computer_name, registered_owner, registered_org, product_id, install_date, format_forensic_timestamp(get_current_utc())))
        else:
            logging.info("Skipping duplicate ComputerNameInfo entry")
        print("Computer name data inserted into database successfully.")
        # Time zone information - Enhanced version
        timeZone_path = "SYSTEM\\CurrentControlSet\\Control\\TimeZoneInformation"
        timezone_reg_key = reg_Claw_live(HKEY_LOCAL_MACHINE, timeZone_path)
        # Extract time zone details
        tz_name = ""
        standard_name = ""
        daylight_name = ""
        bias = 0
        active_bias = 0
        daylight_bias = 0
        standard_start = daylight_start = b""
        dynamic_disabled = None
        for name, (data, value_type) in timezone_reg_key.items():
            low = name.lower()
            if low == "timezonekeyname":
                tz_name = str(data)
            elif low == "standardname":
                standard_name = str(data)
            elif low == "daylightname":
                daylight_name = str(data)
            elif low == "bias":
                try:
                    bias = int(data)
                except Exception:
                    bias = 0
            elif low == "activetimebias":
                try:
                    active_bias = int(data)
                except Exception:
                    active_bias = 0
            elif low == "daylightbias":
                try:
                    daylight_bias = int(data)
                except Exception:
                    daylight_bias = 0
            elif low == "standardstart":
                standard_start = data
            elif low == "daylightstart":
                daylight_start = data
            elif low == "dynamicdaylighttimedisabled":
                dynamic_disabled = data

            # Every value under this key decodes differently - Bias is signed
            # minutes, StandardStart is a recurring rule, StandardName is a
            # resource reference - so the readable form comes from the rule
            # table rather than from str(data), which is what produced
            # "4294967176" and "b'\\x00\\x00\\n\\x00...'".
            decoded = registry_binary_parser.render_registry_value(
                "timezone", name, data, value_type)
            if check_exists(cursor, 'time_zone', ['name', 'row_data', 'type'], (name, str(data), value_type)):
                logging.info(f"Skipping duplicate time_zone entry: {name}")
                continue
            cursor.execute('INSERT OR IGNORE INTO time_zone (name, row_data, decoded, type) VALUES (?, ?, ?, ?)',
                          (name, str(data), decoded, value_type))

        # StandardName and DaylightName are MUI references - "@tzres.dll,-342"
        # - and the English text lives in the SOFTWARE hive of the evidence
        # itself. Read from there rather than through SHLoadIndirectString, so
        # an image acquired from another machine is not described using this
        # analyst's locale.
        def _tz_read(path):
            try:
                return {n: d for n, (d, _t)
                        in reg_Claw_live(HKEY_LOCAL_MACHINE, path).items()}
            except Exception:
                return {}

        resolved = registry_binary_parser.resolve_time_zone_names(
            _tz_read, tz_name)
        # The two name rows hold a resource reference and nothing readable,
        # and the text only exists once the SOFTWARE hive has been consulted -
        # which happens after the raw rows are written. Fill them in now rather
        # than leaving the one column that exists to explain them empty.
        for _col, _val in (("StandardName", resolved["standard_name"]),
                           ("DaylightName", resolved["daylight_name"]),
                           ("TimeZoneKeyName", resolved["display_name"])):
            if _val:
                cursor.execute(
                    'UPDATE time_zone SET decoded = ? WHERE name = ? '
                    'AND (decoded IS NULL OR decoded = ?)', (_val, _col, ""))

        std_rule = registry_binary_parser.parse_tz_transition_rule(standard_start)
        dlt_rule = registry_binary_parser.parse_tz_transition_rule(daylight_start)

        # Cross-check both rules against the TZI blob, which stores the same
        # two transitions in the documented SYSTEMTIME order. The Start values
        # carry wDayOfWeek in a different position, and read the documented way
        # they give an hour of 59 - a wrong answer that raises nothing. Two
        # copies agreeing is what makes the decode trustworthy; a disagreement
        # is recorded rather than resolved silently.
        agrees = ""
        try:
            tzi_blob = _tz_read("%s\\%s" % (
                registry_binary_parser.TIME_ZONES_KEY, tz_name)).get("TZI")
            if tzi_blob:
                checks = [
                    registry_binary_parser.tz_rules_agree(
                        std_rule,
                        registry_binary_parser.tz_rule_from_tzi(tzi_blob, False)),
                    registry_binary_parser.tz_rules_agree(
                        dlt_rule,
                        registry_binary_parser.tz_rule_from_tzi(tzi_blob, True)),
                ]
                if all(c is True for c in checks):
                    agrees = "yes"
                elif any(c is False for c in checks):
                    agrees = "NO - the Start values and TZI disagree"
        except Exception as exc:
            logging.debug("TZI cross-check unavailable: %s", exc)

        signed = registry_binary_parser.signed_bias(bias)
        if not check_exists(cursor, 'TimeZoneInfo', ['time_zone_name', 'standard_name'], (tz_name, resolved["standard_name"] or standard_name)):
            cursor.execute('''
            INSERT INTO TimeZoneInfo
            (time_zone_name, standard_name, daylight_name, bias,
             active_time_bias, daylight_bias, utc_offset, display_name,
             standard_name_raw, daylight_name_raw, standard_start_rule,
             daylight_start_rule, dynamic_dst_disabled, agrees_with_tzi,
             parsed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (tz_name,
             resolved["standard_name"] or standard_name,
             resolved["daylight_name"] or daylight_name,
             signed,
             registry_binary_parser.signed_bias(active_bias),
             registry_binary_parser.signed_bias(daylight_bias),
             registry_binary_parser.utc_offset_label(signed),
             resolved["display_name"],
             standard_name, daylight_name,
             std_rule["rule"], dlt_rule["rule"],
             registry_binary_parser.render_registry_value(
                 "timezone", "DynamicDaylightTimeDisabled", dynamic_disabled, 4)
             if dynamic_disabled is not None else "",
             agrees,
             format_forensic_timestamp(get_current_utc())))
            # DOS date/time in a shell item is local with no zone recorded.
            # Give the decoder the offset rather than letting it relabel.
            registry_binary_parser.set_evidence_bias(bias)
        else:
            logging.info("Skipping duplicate TimeZoneInfo entry")
        print("Time zone information inserted into database successfully.")
        # Network interfaces information - Enhanced version
        networkInterface_path = "SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters\\Interfaces"
        network_interfaces_sub_key = get_subkeys_live(HKEY_LOCAL_MACHINE, networkInterface_path)
        # Process each network interface
        def _mval(data):
            """A REG_MULTI_SZ value as text, not as a Python list literal.

            IPAddress, SubnetMask, DefaultGateway and NameServer are all
            MULTI_SZ, so str() on them wrote "['192.168.56.1']" into columns an
            analyst filters on. The trailing empty strings are the value's NUL
            terminators and are dropped, the same way _fmt does it for the
            autostart tables.
            """
            if isinstance(data, (list, tuple)):
                items = [str(x) for x in data]
                while items and items[-1] == "":
                    items.pop()
                return ", ".join(items)
            return str(data)

        # The only MAC the registry holds, and it is not under this key. The
        # branch that used to fill this column looked for a MacAddress value
        # under Tcpip\Parameters\Interfaces, which does not exist - ten
        # interfaces on a real machine and not one of them had it. So the
        # column was named in the INSERT, filled from a branch that never
        # fired, and empty on every row while looking like it worked.
        #
        # NetworkAddress under the adapter's class key is the real thing, and
        # it is present only when somebody has OVERRIDDEN the burned-in
        # address. Empty means "no override"; populated is a MAC that was set.
        _mac_overrides = {}
        try:
            _cls = ("SYSTEM" + chr(92) + "CurrentControlSet" + chr(92)
                    + "Control" + chr(92) + "Class" + chr(92)
                    + registry_binary_parser.ADAPTER_CLASS_GUID)
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _cls) as _ck:
                for _i in range(winreg.QueryInfoKey(_ck)[0]):
                    _name = winreg.EnumKey(_ck, _i)
                    if not _name.isdigit():
                        continue
                    try:
                        with winreg.OpenKey(_ck, _name) as _ak:
                            _vals = {}
                            for _j in range(winreg.QueryInfoKey(_ak)[1]):
                                _vn, _vd, _ = winreg.EnumValue(_ak, _j)
                                _vals[_vn] = _vd
                    except OSError:
                        continue
                    _guid = _vals.get("NetCfgInstanceId", "")
                    _mac = registry_binary_parser.normalise_mac(
                        _vals.get("NetworkAddress", ""))
                    if _guid and _mac:
                        _mac_overrides[str(_guid).lower()] = _mac
        except Exception as _exc:
            logging.debug("adapter MAC overrides: %s", _exc)
        if _mac_overrides:
            print("[OK] %d network adapter(s) carry a MAC override - a MAC in "
                  "the registry is one somebody set" % len(_mac_overrides))

        for interface_id, values in network_interfaces_sub_key.items():
            static_ip = dhcp_ip = static_mask = dhcp_mask = ""
            ip_address = ""
            subnet_mask = ""
            default_gateway = ""
            dhcp_enabled = 0
            dhcp_server = ""
            dns_servers = ""
            mac_address = _mac_overrides.get(
                str(interface_id).lower(), "")
            gateway_ip = ""
            gateway_hardware_mac = ""
            dns_suffix = ""
            lease_obtained = ""
            lease_expires = ""
            for name, (data, value_type) in values.items():
                # Collected here, resolved after the loop. Accepting either
                # name in one branch meant whichever value enumerated last won,
                # so the same interface could report a different address on two
                # runs of the same parser.
                if name.lower() == "ipaddress":
                    static_ip = _mval(data)
                elif name.lower() == "dhcpipaddress":
                    dhcp_ip = _mval(data)
                elif name.lower() == "subnetmask":
                    static_mask = _mval(data)
                elif name.lower() == "dhcpsubnetmask":
                    dhcp_mask = _mval(data)
                elif name.lower() == "defaultgateway":
                    default_gateway = _mval(data)
                elif name.lower() == "enabledhcp":
                    try:
                        dhcp_enabled = int(data)
                    except:
                        dhcp_enabled = 0
                elif name.lower() == "dhcpserver":
                    dhcp_server = str(data)
                elif name.lower() == "nameserver":
                    dns_servers = _mval(data)

                # The static NameServer/DefaultGateway values exist on almost
                # every interface but are EMPTY on a DHCP client - the assigned
                # values live under the Dhcp* names. Reading only the static
                # ones left both columns blank on all 10 interfaces while two
                # of them really did have a DNS server and one a gateway. Only
                # fill from DHCP when the static value is empty, so a manually
                # configured address still wins.
                elif name.lower() == "dhcpnameserver":
                    if not dns_servers:
                        dns_servers = _mval(data)
                elif name.lower() == "dhcpdefaultgateway":
                    if not default_gateway:
                        default_gateway = _mval(data)
                # The gateway's own hardware address, and a second independent
                # record of something NetworkList also keeps: this yields
                # 04:8C:16:1C:64:9B for gateway 192.168.100.1, and
                # NetworkList\\Signatures records that same MAC as the
                # DefaultGatewayMac of the network named "emad". Two keys
                # written by different components agreeing is worth more than
                # either alone.
                #
                # It is the GATEWAY's MAC. It is deliberately not put in
                # mac_address, which means this adapter's own overridden
                # hardware address and is empty when nobody overrode one.
                elif name.lower() == "dhcpgatewayhardware":
                    _gw = registry_binary_parser.parse_dhcp_gateway_hardware(data)
                    gateway_ip = _gw["gateway_ip"]
                    gateway_hardware_mac = _gw["gateway_mac"]
                elif name.lower() in ("domain", "dhcpdomain"):
                    if not dns_suffix:
                        dns_suffix = str(data)
                elif name.lower() == "leaseobtainedtime":
                    lease_obtained = registry_binary_parser.unix_seconds_label(data)
                elif name.lower() == "leaseterminatestime":
                    lease_expires = registry_binary_parser.unix_seconds_label(data)
                # DhcpGatewayHardware and DhcpInterfaceOptions are blobs
                # and reached this column as a Python bytes repr; the four
                # lease values are Unix epoch seconds and reached it as bare
                # integers, so a lease obtained in September 2025 read as
                # 1757332381 and sorted as text.
                # Keyed on (subkey, name) - one row per registry value, which is
                # what the offline parser has always done. With row_data in the
                # key, a value that legitimately changes between parses (the
                # DHCP lease times renew) was written again, so the table grew
                # on every re-parse of a live machine and never on an image.
                if check_exists(cursor, 'network_interfaces', ['subkey', 'name'], (str(interface_id), name)):
                    logging.info(f"Skipping duplicate network_interfaces entry: {interface_id}/{name}")
                    continue
                # _mval, not str(). A MULTI_SZ value reached this raw dump as a
                # Python list literal, and the two parsers disagreed on the
                # terminators inside it - winreg drops them, python-registry
                # keeps them - so the same interface read "['192.168.56.1']"
                # live and "['192.168.56.1', '', '']" from the hive.
                cursor.execute('INSERT OR IGNORE INTO network_interfaces (subkey, name, row_data, decoded, type) VALUES (?, ?, ?, ?, ?)',
                              (str(interface_id), name, _mval(data),
                               registry_binary_parser.render_registry_value(
                                   'network_interfaces', name, data, value_type),
                               value_type))
            # Static wins over DHCP, the order Windows resolves them and the
            # order the offline parser uses.
            ip_address = static_ip or dhcp_ip
            subnet_mask = static_mask or dhcp_mask
            # Insert into the enhanced table
            if not check_exists(cursor, 'NetworkInterfacesInfo', ['interface_id', 'ip_address'], (interface_id, ip_address)):
                cursor.execute('''
                INSERT INTO NetworkInterfacesInfo
                (interface_id, ip_address, subnet_mask, default_gateway,
                 dhcp_enabled, dhcp_server, dns_servers, mac_address,
                 gateway_ip, gateway_hardware_mac, dns_suffix,
                 lease_obtained, lease_expires, parsed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (interface_id, ip_address, subnet_mask, default_gateway, dhcp_enabled, dhcp_server, dns_servers, mac_address,
                 gateway_ip or None, gateway_hardware_mac or None,
                 dns_suffix or None, lease_obtained or None,
                 lease_expires or None,
                 format_forensic_timestamp(get_current_utc())))
            else:
                logging.info(f"Skipping duplicate NetworkInterfacesInfo entry: {interface_id}")
        print("Network interfaces information inserted into database successfully.")
        # Shutdown information - Enhanced version
        shutdown_path = "SYSTEM\\CurrentControlSet\\Control\\Windows"
        shutdown_reg_key = reg_Claw_live(HKEY_LOCAL_MACHINE, shutdown_path)
        shutdown_time_path = "SYSTEM\\CurrentControlSet\\Control\\SessionManager\\Memory Management\\PrefetchParameters"
        shutdown_time_key = reg_Claw_live(HKEY_LOCAL_MACHINE, shutdown_time_path)
        # Extract shutdown information
        shutdown_time = ""
        shutdown_count = 0
        shutdown_type = ""
        clean_shutdown = 0
        for name, (data, value_type) in shutdown_reg_key.items():
            if name.lower() == "shutdowntime":
                # ShutdownTime is an 8-byte FILETIME, not a string. str()
                # on the blob wrote its Python bytes repr into a column
                # an analyst reads as a shutdown time, and it sorted as
                # text beside the decoded timestamps every other table
                # produces. The offline parser decoded it all along.
                shutdown_time = str(data)
                if isinstance(data, bytes) and len(data) >= 8:
                    try:
                        ft = int.from_bytes(data[:8], 'little')
                        if ft:
                            shutdown_time = format_forensic_timestamp(
                                filetime_to_datetime(ft))
                    except Exception as _e:
                        logging.error("Error parsing ShutdownTime: %s" % _e)
            elif name.lower() == "shutdowncount":
                try:
                    shutdown_count = int(data)
                except:
                    shutdown_count = 0
            elif name.lower() == "shutdowntype":
                shutdown_type = str(data)
            if check_exists(cursor, 'shutdown_information', ['name', 'row_data', 'type'], (name, str(data), value_type)):
                logging.info(f"Skipping duplicate shutdown_information entry: {name}")
                continue
            cursor.execute('INSERT OR IGNORE INTO shutdown_information '
                           '(name, row_data, row_decoded, type) VALUES (?, ?, ?, ?)',
                          (name, str(data),
                           _row_decoded('shutdown_information', name, data, value_type),
                           value_type))
        for name, (data, _) in shutdown_time_key.items():
            if name.lower() == "lastpoweroff":
                try:
                    # Convert Windows timestamp to readable date if possible
                    shutdown_time = format_forensic_timestamp(datetime.datetime.fromtimestamp(int(data), tz=datetime.timezone.utc))
                except:
                    shutdown_time = str(data)
            elif name.lower() == "cleanshutdown":
                try:
                    clean_shutdown = int(data)
                except:
                    clean_shutdown = 0
        # Insert into the enhanced table
        if not check_exists(cursor, 'ShutdownInfo', ['shutdown_time', 'shutdown_type'], (shutdown_time, shutdown_type)):
            cursor.execute('''
            INSERT INTO ShutdownInfo
            (shutdown_time, shutdown_count, shutdown_type, clean_shutdown, parsed_at)
            VALUES (?, ?, ?, ?, ?)''',
            (shutdown_time, shutdown_count, shutdown_type, clean_shutdown, format_forensic_timestamp(get_current_utc())))
        else:
            logging.info("Skipping duplicate ShutdownInfo entry")
        print('Shutdown information inserted into database successfully.')
        # Recent opened docs
        recent_docs_path = "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\RecentDocs"
        # Create a single table for RecentDocs key and subkeys
        # `row_data`, matching the offline parser and the 14 other tables both
        # already agree on. It was `data` here, so the same machine produced a
        # different column name depending on how it was acquired - and anything
        # binding by column name (the correlation engine does) silently missed.
        # One string literal, not two concatenated. A CREATE split across
        # adjacent literals is still valid Python, but the schema readers that
        # parse this file - Sentinel's extract-schema.js and the parity test -
        # see the quote noise in the middle and lose a column.
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS RecentDocs (
            subkey TEXT,
            name TEXT,
            row_data TEXT,
            type TEXT,
            user_name TEXT,
            mru_position INTEGER,
            key_last_write TEXT,
            parsed_at TEXT
        )''')
        # Read and insert data from RecentDocs key.
        #
        # The label is 'main', matching the offline parser. It read 'main key'
        # here, so a query filtering on either one returned nothing on cases
        # acquired the other way - same table, same column, different value.
        recent_docs_key = reg_Claw_live(HKEY_CURRENT_USER, recent_docs_path)
        _rd_order = mru_order_live(recent_docs_key)
        _rd_lastwrite = key_last_write_live(HKEY_CURRENT_USER, recent_docs_path)
        _rd_stamp = format_forensic_timestamp(get_current_utc())
        for name, (data, value_type) in recent_docs_key.items():
            # MRUListEx is the access order, decoded above. It is not a document,
            # and running its index array through the filename decoder stored a
            # garbage string - the offline parser has always skipped it.
            if name.lower() == 'mrulistex':
                continue
            # Parse binary data to extract clean filename
            if value_type == 'REG_BINARY' and isinstance(data, bytes):
                try:
                    # Use the specialized RecentDocs parser
                    parsed_filename = registry_binary_parser.parse_recentdocs_entry(data)

                    # If parsing failed or returned empty, fall back to string representation
                    if not parsed_filename:
                        parsed_filename = str(data)
                        logging.warning(f"RecentDocs parser returned empty for main/{name}, using fallback")
                except Exception as e:
                    logging.error(f"Error parsing RecentDocs entry for main/{name}: {e}")
                    parsed_filename = str(data)
            else:
                # For non-binary data, use string representation
                parsed_filename = str(data)

            mru_position = -1
            try:
                _idx = int(name)
                if _rd_order and _idx in _rd_order:
                    mru_position = _rd_order.index(_idx)
            except (ValueError, TypeError):
                pass

            if check_exists(cursor, 'RecentDocs', ['subkey', 'name', 'row_data', 'type'], ('main', name, parsed_filename, value_type)):
                logging.info(f"Skipping duplicate RecentDocs entry: main/{name}")
                continue
            cursor.execute('INSERT INTO RecentDocs (subkey, name, row_data, type, user_name, mru_position, key_last_write, parsed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                          ('main', name, parsed_filename, value_type, _live_user,
                           mru_position, _rd_lastwrite, _rd_stamp))
        # Read and insert data from RecentDocs subkeys
        recent_docs_subkeys = get_subkeys_live(HKEY_CURRENT_USER, recent_docs_path)
        for subkey, values in recent_docs_subkeys.items():
            # Per-extension ordering and timestamp. Each subkey has its own last
            # write - RecentDocs\.pdf last written is when a PDF was most
            # recently opened - so these are read per subkey, not once.
            _sk_order = mru_order_live(values)
            _sk_lastwrite = key_last_write_live(
                HKEY_CURRENT_USER, f"{recent_docs_path}\\{subkey}")
            for name, (data, value_type) in values.items():
                if name.lower() == 'mrulistex':
                    continue
                # Parse binary data to extract clean filename
                if value_type == 'REG_BINARY' and isinstance(data, bytes):
                    try:
                        # Use the specialized RecentDocs parser
                        parsed_filename = registry_binary_parser.parse_recentdocs_entry(data)

                        # If parsing failed or returned empty, fall back to string representation
                        if not parsed_filename:
                            parsed_filename = str(data)
                            logging.warning(f"RecentDocs parser returned empty for {subkey}/{name}, using fallback")
                    except Exception as e:
                        logging.error(f"Error parsing RecentDocs entry for {subkey}/{name}: {e}")
                        parsed_filename = str(data)
                else:
                    # For non-binary data, use string representation
                    parsed_filename = str(data)

                mru_position = -1
                try:
                    _idx = int(name)
                    if _sk_order and _idx in _sk_order:
                        mru_position = _sk_order.index(_idx)
                except (ValueError, TypeError):
                    pass

                if check_exists(cursor, 'RecentDocs', ['subkey', 'name', 'row_data', 'type'], (subkey, name, parsed_filename, value_type)):
                    logging.info(f"Skipping duplicate RecentDocs entry: {subkey}/{name}")
                    continue
                cursor.execute('INSERT INTO RecentDocs (subkey, name, row_data, type, user_name, mru_position, key_last_write, parsed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                              (subkey, name, parsed_filename, value_type, _live_user,
                               mru_position, _sk_lastwrite, _rd_stamp))
        print("RecentDocs key and subkeys data inserted into database successfully.")
        typed_paths_key_path = "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\TypedPaths"
        # Create table for TypedPaths key
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS TypedPaths (
            name TEXT,
            row_data TEXT,
            type TEXT,
            user_name TEXT,
            mru_position INTEGER,
            key_last_write TEXT,
            parsed_at TEXT
        )''')
        typed_paths_key = reg_Claw_live(HKEY_CURRENT_USER, typed_paths_key_path)
        # TypedPaths has no MRUListEx - the order is in the value name, url1
        # being the most recent. Normalised to the same 0-based position every
        # other MRU table uses.
        _tp_lastwrite = key_last_write_live(HKEY_CURRENT_USER, typed_paths_key_path)
        _tp_stamp = format_forensic_timestamp(get_current_utc())
        for name, (data, value_type) in typed_paths_key.items():
            mru_position = -1
            if name[:3].lower() == 'url' and name[3:].isdigit():
                mru_position = int(name[3:]) - 1
            if check_exists(cursor, 'TypedPaths', ['name', 'row_data', 'type'], (name, str(data), value_type)):
                logging.info(f"Skipping duplicate TypedPaths entry: {name}")
                continue
            cursor.execute('INSERT INTO TypedPaths (name, row_data, type, user_name, mru_position, key_last_write, parsed_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                          (name, str(data), value_type, _live_user,
                           mru_position, _tp_lastwrite, _tp_stamp))
        print("TypedPaths data inserted into database successfully.")
        # Files that have been opened or saved by Windows shell dialog box - Enhanced version
        shellbags_path = "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\ComDlg32\\OpenSavePidlMRU"
        try:
            shellbags_subkeys = get_subkeys_live(HKEY_CURRENT_USER, shellbags_path)
            for subkey, values in shellbags_subkeys.items():
                # First, parse MRUListEx to get access order
                mru_order = []
                if 'mrulistex' in [k.lower() for k in values.keys()]:
                    mrulistex_key = [k for k in values.keys() if k.lower() == 'mrulistex'][0]
                    mrulistex_data, mrulistex_type = values[mrulistex_key]
                    if isinstance(mrulistex_data, bytes):
                        try:
                            mru_order = registry_binary_parser.parse_mru_list_ex(mrulistex_data)
                            logging.debug(f"Parsed MRUListEx for {subkey}: {mru_order}")
                        except Exception as e:
                            logging.error(f"Error parsing MRUListEx for {subkey}: {e}")
               
                # Get the registry key's last write time (most recent access)
                try:
                    with winreg.OpenKey(HKEY_CURRENT_USER, f"{shellbags_path}\\{subkey}") as key:
                        # Get key info: (num_subkeys, num_values, last_modified_filetime)
                        key_info = winreg.QueryInfoKey(key)
                        last_write_time_ns = key_info[2] # FILETIME in 100-nanosecond intervals
                       
                        # Convert to datetime
                        if last_write_time_ns > 0:
                            # Convert from Windows FILETIME to Unix timestamp
                            FILETIME_EPOCH_DIFF = 116444736000000000
                            microseconds = (last_write_time_ns - FILETIME_EPOCH_DIFF) / 10
                            last_write_dt = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc) + datetime.timedelta(microseconds=microseconds)
                            most_recent_access = format_forensic_timestamp(last_write_dt)
                        else:
                            most_recent_access = ""
                except Exception as e:
                    logging.error(f"Error getting last write time for {subkey}: {e}")
                    most_recent_access = ""
               
                for name, (data, value_type) in values.items():
                    file_path = ""
                    file_name = ""
                    extension = subkey # The subkey is often the file extension
                    drive_letter = ""
                    access_date = ""
                    # Skip MRUListEx entries - they're just ordering information
                    if name.lower() == 'mrulistex':
                        continue
                    # Determine access order/recency
                    try:
                        entry_index = int(name)
                        if mru_order and entry_index in mru_order:
                            # Position in MRU list (0 = most recent)
                            mru_position = mru_order.index(entry_index)
                            # access_date stays empty. An MRU list carries no
                            # per-entry time, so giving the key's last-write to
                            # whichever entry is at position 0 attributes a key
                            # fact to one row that may not have caused it. It
                            # was also written as
                            # "2026-08-18 08:48:37 (Registry Key LastWrite)" -
                            # text appended to a timestamp column, which stops
                            # it sorting or comparing as a time at all. The fact
                            # is kept, in key_last_write, where RunMRU and
                            # WordWheelQuery already keep it.
                    except (ValueError, TypeError):
                        pass # Name is not a number
                    # Try to extract file path from MRU data using specialized parser
                    if value_type == "REG_BINARY" and isinstance(data, bytes):
                        try:
                            # Use the specialized binary parser for OpenSaveMRU entries
                            parsed_data = registry_binary_parser.parse_opensavemru_entry(data)
                            file_path = parsed_data.get('file_path', '')
                            file_name = parsed_data.get('file_name', '')
                            drive_letter = parsed_data.get('drive_letter', '')
                            if parsed_data.get('extension'):
                                extension = parsed_data.get('extension')
                            # Use parser's timestamp if available and we don't have one from MRU
                            if parsed_data.get('access_date') and not access_date:
                                access_date = parsed_data.get('access_date', '')
                        except Exception as e:
                            # Fallback to original string representation on parse failure
                            logging.error(f"Error parsing OpenSaveMRU entry {subkey}/{name}: {e}")
                            try:
                                # Fallback: try simple UTF-16-LE decode
                                possible_path = data.decode('utf-16-le', errors='ignore').strip('\x00')
                                clean_path = ''.join(c for c in possible_path if c.isprintable() or c in [' ', '\\', '/', '.', ':', '-'])
                                if '\\' in clean_path and len(clean_path) > 5:
                                    file_path = clean_path
                                    # Extract file name from path
                                    if '\\' in file_path:
                                        file_name = file_path.split('\\')[-1]
                            except:
                                pass
                   
                    if check_exists(cursor, 'OpenSaveMRU', ['subkey', 'name', 'row_data', 'type'], (subkey, name, str(data), value_type)):
                        logging.info(f"Skipping duplicate OpenSaveMRU entry: {subkey}/{name}")
                        continue
                    cursor.execute('INSERT INTO OpenSaveMRU (subkey, name, type, file_path, file_name, extension, drive_letter, access_date, key_last_write, row_data, parsed_at, user_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                                  (subkey, name, value_type, file_path, file_name, extension, drive_letter, access_date, most_recent_access, str(data), format_forensic_timestamp(get_current_utc()), _live_user))
            print("OpenSaveMRU subkeys data inserted into database successfully with enhanced information.")
        except Exception as e:
            logging.error(f"Error accessing OpenSavePidlMRU: {e}")
        # Track directories that were accessed by applications - Enhanced version
        last_savemru_path = "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\ComDlg32\\LastVisitedPidlMRU"
        try:
            lastsavemru_regkey = reg_Claw_live(HKEY_CURRENT_USER, last_savemru_path)
            # Parse MRUListEx to get access order
            mru_order = []
            if 'MRUListEx' in lastsavemru_regkey:
                mrulistex_data, mrulistex_type = lastsavemru_regkey['MRUListEx']
                if isinstance(mrulistex_data, bytes):
                    try:
                        mru_order = registry_binary_parser.parse_mru_list_ex(mrulistex_data)
                        logging.debug(f"Parsed LastSaveMRU MRUListEx: {mru_order}")
                    except Exception as e:
                        logging.error(f"Error parsing LastSaveMRU MRUListEx: {e}")
           
            # Get the registry key's last write time
            try:
                with winreg.OpenKey(HKEY_CURRENT_USER, last_savemru_path) as key:
                    key_info = winreg.QueryInfoKey(key)
                    last_write_time_ns = key_info[2]
                   
                    if last_write_time_ns > 0:
                        FILETIME_EPOCH_DIFF = 116444736000000000
                        microseconds = (last_write_time_ns - FILETIME_EPOCH_DIFF) / 10
                        last_write_dt = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc) + datetime.timedelta(microseconds=microseconds)
                        most_recent_access = format_forensic_timestamp(last_write_dt)
                    else:
                        most_recent_access = ""
            except Exception as e:
                logging.error(f"Error getting last write time for LastSaveMRU: {e}")
                most_recent_access = ""
            for name, (data, value_type) in lastsavemru_regkey.items():
                folder_path = ""
                folder_name = ""
                application = ""
                drive_letter = ""
                access_date = ""
                # Skip MRUListEx - we already parsed it
                if name.lower() == 'mrulistex':
                    continue
                
                # Parse binary data using specialized parser first to get application name
                if value_type == "REG_BINARY" and isinstance(data, bytes):
                    try:
                        # Use the specialized LastSaveMRU parser
                        parsed_data = registry_binary_parser.parse_lastsavemru_entry(data)
                        application = parsed_data.get('application', '')
                        folder_path = parsed_data.get('folder_path', '')
                        folder_name = parsed_data.get('file_name', '')  # file_name contains folder name
                        drive_letter = parsed_data.get('drive_letter', '')
                       
                        # Log successful parsing
                        if application or folder_path:
                            logging.debug(f"Successfully parsed LastSaveMRU entry '{name}': app={application}, folder={folder_path}")
                    except Exception as e:
                        # Fallback to string representation on parse failure
                        logging.error(f"Error parsing LastSaveMRU entry '{name}': {e}")
                        try:
                            # Fallback: try simple UTF-16-LE decode
                            text_data = data.decode('utf-16-le', errors='ignore').strip('\x00')
                            parts = text_data.split('\x00')
                            clean_parts = [''.join(c for c in part if c.isprintable() or c in [' ', '\\', '/', '.', ':', '-'])
                                          for part in parts if part.strip()]
                            if clean_parts:
                                if len(clean_parts) > 0 and len(clean_parts[0]) > 1:
                                    application = clean_parts[0]
                                for part in clean_parts:
                                    if '\\' in part and len(part) > 5:
                                        folder_path = part
                                        # Extract folder name from path
                                        if '\\' in folder_path:
                                            folder_name = folder_path.split('\\')[-1]
                                        break
                        except:
                            pass
                
                # Determine access order/recency.
                #
                # access_date stays empty, for the same reason as OpenSaveMRU
                # above: the key's last-write is a fact about the key, not about
                # whichever entry happens to sit at MRU position 0. It is
                # recorded in key_last_write instead.
                try:
                    entry_index = int(name)
                    if mru_order and entry_index in mru_order:
                        mru_position = mru_order.index(entry_index)
                except (ValueError, TypeError):
                    pass
               
                if check_exists(cursor, 'LastSaveMRU', ['mru_number', 'row_data', 'type'], (name, str(data), value_type)):
                    logging.info(f"Skipping duplicate LastSaveMRU entry: {name}")
                    continue
                cursor.execute('INSERT INTO LastSaveMRU (mru_number, type, application, folder_path, folder_name, drive_letter, access_date, key_last_write, row_data, parsed_at, user_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                              (name, value_type, application, folder_path, folder_name, drive_letter, access_date, most_recent_access, str(data), format_forensic_timestamp(get_current_utc()), _live_user))
            print("LastSaveMRU has been inserted into database successfully with enhanced information.")
        except Exception as e:
            logging.error(f"Error accessing LastVisitedPidlMRU: {e}")
        # DAM is collected once, above, alongside BAM. A second collector sat
        # here naming a 'data' column that DAM does not have (it is row_data).
        # check_exists swallows the resulting error and returns False, so its
        # guard always said 'not present', and the INSERT that followed then
        # failed on the same wrong column - taking the rest of the block with
        # it into the outer except. It could never write a row.
        # Get USB storage device information from multiple registry locations
        try:
            # Check USBSTOR devices
            usbstor_path = "SYSTEM\\CurrentControlSet\\Enum\\USBSTOR"
            # The acquired SYSTEM hive, for the device-property times below.
            # These three calls used to name `_sys_hive`, which nothing ever
            # assigned: the block raised NameError on the FIRST device, the
            # outer except swallowed it, and USBStorageDevices and
            # USBStorageVolumes came out empty on every live case - with the
            # log still reporting "USB devices information inserted
            # successfully" from the neighbouring block. Acquired here, before
            # the loop, because the memoised copy has to outlive every
            # iteration; the context-manager form deletes it on exit.
            _sys_hive, _usbstor_route = live_hive_access.acquired_hive(
                "SYSTEM",
                allow_snapshot_creation=_parser_allows_snapshot_creation())
            usbstor_subkeys = get_subkeys_live(HKEY_LOCAL_MACHINE, usbstor_path)
            for device_class, device_values in usbstor_subkeys.items():
                # Parse device class (usually in format Disk&Ven_[Vendor]&Prod_[Product]&Rev_[Revision])
                vendor_id = ""
                product_id = ""
                revision = ""
                parts = device_class.split('&')
                for part in parts:
                    if part.startswith('Ven_'):
                        vendor_id = part[4:]
                    elif part.startswith('Prod_'):
                        product_id = part[5:]
                    elif part.startswith('Rev_'):
                        revision = part[4:]
                # For each device instance (usually serial number)
                for serial_number, instance_values in get_subkeys_live(HKEY_LOCAL_MACHINE, f"{usbstor_path}\\{device_class}").items():
                    friendly_name = ""
                    first_connected = ""
                    last_connected = ""
                    last_removed = ""
                    # Get instance properties
                    for name, (data, _) in instance_values.items():
                        if name.lower() == "friendlyname":
                            friendly_name = str(data)
                        elif name.lower() == "devicedesc":
                            if not friendly_name: # Use DeviceDesc if FriendlyName not available
                                friendly_name = str(data)
                    # The connection times, from the acquired hive. These keys
                    # deny winreg even to an elevated administrator, so the
                    # three blocks that used to ask for them here could never
                    # succeed: every live case had these columns empty.
                    #
                    # 0065 first install, 0066 LAST ARRIVAL, 0067 LAST REMOVAL.
                    first_connected = _live_device_property_time(
                        _sys_hive, "Enum" + chr(92) + "USBSTOR", device_class,
                        serial_number, "0065")
                    last_connected = _live_device_property_time(
                        _sys_hive, "Enum" + chr(92) + "USBSTOR", device_class,
                        serial_number, "0066")
                    last_removed = _live_device_property_time(
                        _sys_hive, "Enum" + chr(92) + "USBSTOR", device_class,
                        serial_number, "0067")
               
                    # Insert into USB storage devices table
                    cursor.execute('''
                    INSERT OR IGNORE INTO USBStorageDevices
                    (device_id, friendly_name, serial_number, vendor_id, product_id, revision, first_connected, last_connected, last_removed, parsed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (f"{device_class}\\{serial_number}", friendly_name, serial_number, vendor_id, product_id, revision,
                     first_connected, last_connected, last_removed, format_forensic_timestamp(get_current_utc())))
            print("USB storage device information inserted into database successfully.")
            # Try to get volume information from mounted devices
            try:
                mounted_devices_path = "SYSTEM\\MountedDevices"
                mounted_devices = reg_Claw_live(HKEY_LOCAL_MACHINE, mounted_devices_path)
                volume_count = 0
                for name, (data, _) in mounted_devices.items():
                    if name.startswith('\\DosDevices\\') or name.startswith('\\??\\Volume'):
                        drive_letter = ""
                        volume_guid = ""
                        if name.startswith('\\DosDevices\\'):
                            drive_letter = name[12:] # Extract drive letter
                        elif name.startswith('\\??\\Volume'):
                            volume_guid = name[11:] # Extract volume GUID
                        if isinstance(data, bytes):
                            def _extract_usbstor(data_bytes):
                                try:
                                    s = data_bytes.decode('utf-16-le', errors='ignore') if isinstance(data_bytes, bytes) else str(data_bytes)
                                except Exception:
                                    s = str(data_bytes)
                                sl = s.lower()
                                if 'usbstor#' not in sl:
                                    return None
                                start = sl.find('usbstor#') + len('usbstor#')
                                end = sl.find('#{', start)
                                if end == -1:
                                    return None
                                inst = s[start:end]
                                parts = inst.split('#')
                                if len(parts) < 2:
                                    return None
                                dev_class = parts[0]
                                instance = parts[1]
                                def _norm_class(dc):
                                    p = dc.split('&')
                                    out = []
                                    for x in p:
                                        xl = x.lower()
                                        if xl.startswith('disk'):
                                            out.append('Disk')
                                        elif xl.startswith('ven_'):
                                            out.append('Ven_' + x.split('_',1)[1])
                                        elif xl.startswith('prod_'):
                                            out.append('Prod_' + x.split('_',1)[1])
                                        elif xl.startswith('rev_'):
                                            out.append('Rev_' + x.split('_',1)[1])
                                        else:
                                            out.append(x)
                                    return '&'.join(out)
                                return _norm_class(dev_class), instance
                            extracted = _extract_usbstor(data)
                            if extracted:
                                norm_class, instance = extracted
                                candidate_id = f"{norm_class}\\{instance}"
                                try:
                                    row = cursor.execute('SELECT device_id FROM USBStorageDevices WHERE device_id = ?', (candidate_id,)).fetchone()
                                    if row:
                                        if check_exists(cursor, 'USBStorageVolumes', ['device_id', 'volume_guid'], (candidate_id, volume_guid)):
                                            logging.info(f"Skipping duplicate USBStorageVolumes entry: {candidate_id}/{volume_guid}")
                                        else:
                                            cursor.execute('''
                                            INSERT OR IGNORE INTO USBStorageVolumes
                                            (device_id, volume_guid, volume_name, drive_letter, parsed_at)
                                            VALUES (?, ?, ?, ?, ?)''',
                                            (candidate_id, volume_guid, "", drive_letter, format_forensic_timestamp(get_current_utc())))
                                            volume_count += 1
                                except sqlite3.OperationalError as e:
                                    logging.error(f"Error querying USBStorageDevices table: {e}")
                print(f"USB storage volume information inserted into database successfully. Found {volume_count} volumes.")
            except Exception as e:
                logging.error(f"Error accessing mounted devices: {e}")
        except Exception as e:
            logging.error(f"Error accessing USB storage devices: {e}")
        # Try to get Internet Explorer/Edge history from TypedURLs
        try:
            typed_urls_path = "Software\\Microsoft\\Internet Explorer\\TypedURLs"
            typed_urls = reg_Claw_live(HKEY_CURRENT_USER, typed_urls_path)
            # TypedURLsTime holds an 8-byte FILETIME per urlN - the only time
            # this artifact records, and neither parser read it. Absent before
            # Windows 8, so a missing key is normal, not an error.
            typed_urls_time = reg_Claw_live(
                HKEY_CURRENT_USER, "Software\\Microsoft\\Internet Explorer\\TypedURLsTime")
            for name, (url, _) in typed_urls.items():
                # TypedURLs are stored as url1, url2, etc.
                when = ""
                _t = typed_urls_time.get(name)
                if _t and isinstance(_t[0], bytes):
                    try:
                        when = registry_binary_parser.parse_filetime(_t[0]) or ""
                    except Exception as e:
                        logging.debug(f"TypedURLsTime {name}: {e}")
                # "Internet Explorer" - the key belongs to IE, and the offline
                # parser has always said so. This read "Internet Explorer/Edge",
                # so a filter on the browser column matched only one of them.
                if check_exists(cursor, 'BrowserHistory',
                                ['browser', 'url', 'user_name'],
                                ("Internet Explorer", str(url), _live_user)):
                    logging.info(f"Skipping duplicate BrowserHistory entry: {url}")
                    continue
                cursor.execute('''
                INSERT INTO BrowserHistory
                (browser, url, title, visit_count, last_visit, parsed_at, user_name)
                VALUES (?, ?, ?, ?, ?, ?, ?)''',
                ("Internet Explorer", str(url), "", 0, when,
                 format_forensic_timestamp(get_current_utc()), _live_user))
            print("Browser history from registry inserted into database successfully.")
        except Exception as e:
            logging.error(f"Error accessing browser history: {e}")
        # Get installed software from registry
        try:
            # 64-bit applications
            software_path = "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall"
            software_keys = get_subkeys_live(HKEY_LOCAL_MACHINE, software_path)
            # Process each software entry
            for app_id, values in software_keys.items():
                display_name = ""
                display_version = ""
                publisher = ""
                install_date = ""
                install_location = ""
                uninstall_string = ""
                for name, (data, _) in values.items():
                    if name.lower() == "displayname":
                        display_name = str(data)
                    elif name.lower() == "displayversion":
                        display_version = str(data)
                    elif name.lower() == "publisher":
                        publisher = str(data)
                    elif name.lower() == "installdate":
                        install_date = str(data)
                    elif name.lower() == "installlocation":
                        install_location = str(data)
                    elif name.lower() == "uninstallstring":
                        uninstall_string = str(data)
                # An Uninstall subkey with no DisplayName is still an
                # installed-software record: AddressBook, Connection Manager,
                # DXM_Runtime and 17 others on this machine. Skipping them
                # dropped 20 entries the offline parser has always kept, which
                # falls back to the subkey name for exactly this case.
                if not display_name:
                    display_name = str(app_id)

                if display_name:
                    if check_exists(cursor, 'InstalledSoftware', ['display_name', 'display_version'], (display_name, display_version)):
                        logging.info(f"Skipping duplicate InstalledSoftware entry: {display_name}")
                        continue
                    cursor.execute('''
                    INSERT INTO InstalledSoftware
                    (display_name, display_version, publisher, install_date, install_location, uninstall_string, parsed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)''',
                    (display_name, display_version, publisher,
                     registry_binary_parser.normalise_install_date(install_date),
                     install_location, uninstall_string,
                     format_forensic_timestamp(get_current_utc())))
            # 32-bit applications on 64-bit Windows
            software_path_32 = "SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall"
            try:
                software_keys_32 = get_subkeys_live(HKEY_LOCAL_MACHINE, software_path_32)
                # Process each 32-bit software entry
                for app_id, values in software_keys_32.items():
                    display_name = ""
                    display_version = ""
                    publisher = ""
                    install_date = ""
                    install_location = ""
                    uninstall_string = ""
                    for name, (data, _) in values.items():
                        if name.lower() == "displayname":
                            display_name = str(data)
                        elif name.lower() == "displayversion":
                            display_version = str(data)
                        elif name.lower() == "publisher":
                            publisher = str(data)
                        elif name.lower() == "installdate":
                            install_date = str(data)
                        elif name.lower() == "installlocation":
                            install_location = str(data)
                        elif name.lower() == "uninstallstring":
                            uninstall_string = str(data)
                    # Only insert if there's a display name (filters out some system components)
                    if display_name:
                        if check_exists(cursor, 'InstalledSoftware', ['display_name', 'display_version'], (display_name, display_version)):
                            logging.info(f"Skipping duplicate InstalledSoftware entry: {display_name}")
                            continue
                        cursor.execute('''
                        INSERT INTO InstalledSoftware
                        (display_name, display_version, publisher, install_date, install_location, uninstall_string, parsed_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)''',
                        (display_name, display_version, publisher,
                         registry_binary_parser.normalise_install_date(install_date),
                         install_location, uninstall_string,
                         format_forensic_timestamp(get_current_utc())))
            except Exception as e:
                logging.error(f"Error accessing 32-bit software registry: {e}")
       
            print("Installed software information inserted into database successfully.")
        except Exception as e:
            logging.error(f"Error accessing installed software: {e}")
        # Get system services from registry
        try:
            services_path = "SYSTEM\\CurrentControlSet\\Services"
            services = get_subkeys_live(HKEY_LOCAL_MACHINE, services_path)
            for service_name, values in services.items():
                display_name = ""
                description = ""
                image_path = ""
                start_type = 0
                service_type = 0
                error_control = 0
                for name, (data, _) in values.items():
                    if name.lower() == "displayname":
                        display_name = str(data)
                    elif name.lower() == "description":
                        description = str(data)
                    elif name.lower() == "imagepath":
                        image_path = str(data)
                    elif name.lower() == "start":
                        try:
                            start_type = int(data)
                        except:
                            start_type = 0
                    elif name.lower() == "type":
                        try:
                            service_type = int(data)
                        except:
                            service_type = 0
                    elif name.lower() == "errorcontrol":
                        try:
                            error_control = int(data)
                        except:
                            error_control = 0
                # Determine service status (this is a best guess from registry, not real-time status)
                status = "Unknown"
                if start_type == 4:
                    status = "Disabled"
                elif start_type == 2:
                    status = "Auto Start"
                elif start_type == 3:
                    status = "Manual"
                elif start_type == 0:
                    status = "Boot"
                cursor.execute('''
                INSERT OR IGNORE INTO SystemServices
                (service_name, display_name, description, image_path, start_type, service_type, error_control, status, parsed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (service_name, display_name, description, image_path, start_type, service_type, error_control, status,
                 format_forensic_timestamp(get_current_utc())))
            print("System services information inserted into database successfully.")
        except Exception as e:
            logging.error(f"Error accessing system services: {e}")
        # Get general USB devices information
        try:
            usb_path = "SYSTEM\\CurrentControlSet\\Enum\\USB"
            usb_devices = get_subkeys_live(HKEY_LOCAL_MACHINE, usb_path)
            for device_id, device_values in usb_devices.items():
                # For each device instance
                for instance_id, instance_values in get_subkeys_live(HKEY_LOCAL_MACHINE, f"{usb_path}\\{device_id}").items():
                    description = ""
                    manufacturer = ""
                    friendly_name = ""
                    last_connected = ""
                    # Get instance properties
                    for name, (data, _) in instance_values.items():
                        if name.lower() == "devicedesc":
                            description = str(data)
                        elif name.lower() == "mfg":
                            manufacturer = str(data)
                        elif name.lower() == "friendlyname":
                            friendly_name = str(data)
                    # The last connected time, from the acquired hive. This
                    # key denies winreg even elevated, so the block that used to
                    # ask for it here could never succeed - the column was empty
                    # on every row of every live case.
                    _sys_usb_hive, _usb_route = live_hive_access.acquired_hive(
                        "SYSTEM",
                        allow_snapshot_creation=_parser_allows_snapshot_creation())
                    last_connected = _live_device_property_time(
                        _sys_usb_hive, "Enum" + chr(92) + "USB", device_id,
                        instance_id, "0066")
               
                    # Insert into USB devices table
                    cursor.execute('''
                    INSERT OR IGNORE INTO USBDevices
                    (device_id, description, manufacturer, friendly_name, last_connected)
                    VALUES (?, ?, ?, ?, ?)''',
                    (f"{device_id}\\{instance_id}", description, manufacturer, friendly_name, last_connected))
                    # Get additional properties
                    try:
                        properties_path = f"SYSTEM\\CurrentControlSet\\Enum\\USB\\{device_id}\\{instance_id}\\Properties"
                        property_categories = get_subkeys_live(HKEY_LOCAL_MACHINE, properties_path)
                        for category_id, category_values in property_categories.items():
                            for property_id, property_values in get_subkeys_live(HKEY_LOCAL_MACHINE, f"{properties_path}\\{category_id}").items():
                                for value_name, (data, value_type) in property_values.items():
                                    property_name = f"{category_id}\\{property_id}\\{value_name}"
                                    property_value = data.hex() if isinstance(data, bytes) else str(data)
                                    cursor.execute('''
                                    INSERT OR IGNORE INTO USBProperties
                                    (device_id, property_name, property_value, property_type)
                                    VALUES (?, ?, ?, ?)''',
                                    (f"{device_id}\\{instance_id}", property_name, property_value, value_type))
                    except Exception as e:
                        logging.error(f"Error accessing USB properties for {device_id}\\{instance_id}: {e}")
               
                    # Get parent information
                    parent_id = ""
                    service = ""
                    status = ""
                    try:
                        for name, (data, _) in instance_values.items():
                            # ParentIdPrefix is the value the instance key
                            # actually holds. "Parent" is a devnode property,
                            # not a registry value, so this matched nothing and
                            # left parent_id empty on every row while the
                            # offline parser filled twelve of them.
                            if name.lower() == "parentidprefix":
                                parent_id = str(data)
                            elif name.lower() == "service":
                                service = str(data)
                            elif name.lower() == "status":
                                status = str(data)
                        # status is whatever the key says, which is usually
                        # nothing. It used to be derived - "Removed" if the
                        # instance id contained that word, "Present" otherwise -
                        # which wrote "Present" on all 21 rows. That is a claim
                        # that the device is attached now, and an Enum key cannot
                        # support it: it records that a device was enumerated
                        # once, not that it is plugged in.
                        cursor.execute('''
                        INSERT OR IGNORE INTO USBInstances
                        (device_id, instance_id, parent_id, service, status)
                        VALUES (?, ?, ?, ?, ?)''',
                        (f"{device_id}", instance_id, parent_id, service, status))
                    except Exception as e:
                        logging.error(f"Error processing USB instance for {device_id}\\{instance_id}: {e}")
               
            print("USB devices information inserted into database successfully.")
        except Exception as e:
            logging.error(f"Error accessing USB devices: {e}")
        
        # Collect user profile information
        try:
            print("Collecting user profile information...")
            
            # Get user profiles from ProfileList
            # This registry key is accessible with standard admin privileges
            profile_list_path = "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\ProfileList"
            profile_subkeys = get_subkeys_live(HKEY_LOCAL_MACHINE, profile_list_path)
            
            user_count = 0
            
            for sid, profile_values in profile_subkeys.items():
                try:
                    # Every ProfileList entry is recorded, service SIDs
                    # included. Skipping anything without an S-1-5-21 prefix
                    # dropped three of the four profiles this key actually
                    # holds, and made the live parser disagree with the offline
                    # one about the same artifact - the offline parser has
                    # always recorded all four. A table named for the artifact
                    # reports what the artifact contains; deciding that
                    # S-1-5-18 is uninteresting is the analyst's call, not the
                    # parser's.
                    
                    # Extract profile information from ProfileList
                    profile_path = ""
                    profile_image_path = ""
                    profile_loaded = 0
                    
                    for name, (data, value_type) in profile_values.items():
                        if name.lower() == "profileimagepath":
                            profile_image_path = str(data)
                            # profile_path is the profile's path. It held the leaf
                            # directory name instead, so a column an analyst reads
                            # as a location said "Ghass", and the service profiles
                            # under ServiceProfiles were indistinguishable from a
                            # user account of the same name. The leaf name is what
                            # username wants, and it is derived from the path below.
                            profile_path = profile_image_path
                        elif name.lower() == "state":
                            # State 0 = loaded, 256 = unloaded
                            try:
                                state = int(data)
                                profile_loaded = 1 if state == 0 else 0
                            except:
                                pass
                    
                    # Use profile directory name as username
                    username = (profile_image_path.rsplit('\\', 1)[-1]
                                if profile_image_path else "")
                    if not username:
                        username = "Unknown"
                    
                    # Insert user profile data into database
                    cursor.execute('''
                    INSERT OR REPLACE INTO UserProfiles
                    (user_sid, username, profile_path, profile_image_path, profile_loaded, parsed_at)
                    VALUES (?, ?, ?, ?, ?, ?)''',
                    (sid, username, profile_path, profile_image_path, profile_loaded, 
                     format_forensic_timestamp(get_current_utc())))
                    
                    user_count += 1
                    
                except Exception as e:
                    logging.error(f"Error processing user profile {sid}: {e}")
                    continue
            
            # Report collection results
            print(f"User profile information collected successfully. Total users: {user_count}")
            print(f"  [OK] Collected: User SIDs, usernames, profile paths, and load status")
            
        except Exception as e:
            logging.error(f"Error collecting user profile information: {e}")
            print(f"Warning: Could not collect complete user profile information: {e}")
        
        # MUICache is collected once, above, over both of its registry paths and
        # through registry_binary_parser.parse_muicache_entry. A second collector
        # used to sit here with its own hand-written suffix list, so the same
        # value normalised differently depending on which block reached it first
        # and the second one's rows were then dropped as duplicates.

        # ------------------------------------------------------------------
        # Scheduled Tasks (TaskCache)
        #
        # SOFTWARE\Microsoft\Windows NT\CurrentVersion\Schedule\TaskCache.
        # Note the hive: SYSTEM\CurrentControlSet\Services\Schedule exists but
        # holds no TaskCache, so aiming there yields zero rows and no error.
        #
        # Tree maps a human task path to the {GUID} used under Tasks, and the
        # Plain/Logon/Boot/Maintenance keys index the same GUIDs by trigger
        # type - membership is a persistence signal without decoding Triggers.
        # ------------------------------------------------------------------
        try:
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS ScheduledTasks (
                task_path TEXT,
                task_guid TEXT PRIMARY KEY,
                command TEXT,
                arguments TEXT,
                working_dir TEXT,
                run_context TEXT,
                triggers_index TEXT,
                task_registered TEXT,
                last_run TEXT,
                last_completed TEXT,
                last_result INTEGER,
                parsed_at TEXT
            )''')

            TASKCACHE = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Schedule\TaskCache"

            def _tc_tree_map():
                r"""{GUID} -> human task path, walked from TaskCache\Tree."""
                mapping = {}

                def walk(key, prefix):
                    idx = 0
                    while True:
                        try:
                            child = winreg.EnumKey(key, idx)
                        except OSError:
                            break
                        idx += 1
                        try:
                            sub = winreg.OpenKey(key, child)
                        except OSError:
                            continue
                        with sub:
                            try:
                                mapping[str(winreg.QueryValueEx(sub, "Id")[0]).upper()] = prefix + "\\" + child
                            except FileNotFoundError:
                                pass  # a folder, not a task
                            walk(sub, prefix + "\\" + child)

                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, TASKCACHE + r"\Tree") as tree:
                        walk(tree, "")
                except OSError as e:
                    logging.warning(f"TaskCache\\Tree unavailable: {e}")
                return mapping

            def _tc_trigger_map():
                """{GUID} -> which trigger buckets it appears in."""
                membership = {}
                for bucket in ("Plain", "Logon", "Boot", "Maintenance"):
                    try:
                        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, TASKCACHE + "\\" + bucket) as bk:
                            idx = 0
                            while True:
                                try:
                                    g = winreg.EnumKey(bk, idx).upper()
                                except OSError:
                                    break
                                idx += 1
                                membership.setdefault(g, []).append(bucket)
                    except OSError:
                        continue
                return membership

            tree_map = _tc_tree_map()
            trigger_map = _tc_trigger_map()
            task_count = 0

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, TASKCACHE + r"\Tasks") as tasks_key:
                idx = 0
                while True:
                    try:
                        guid = winreg.EnumKey(tasks_key, idx)
                    except OSError:
                        break
                    idx += 1
                    try:
                        task_key = winreg.OpenKey(tasks_key, guid)
                    except OSError:
                        continue
                    with task_key:
                        guid_u = guid.upper()
                        try:
                            reg_path = winreg.QueryValueEx(task_key, "Path")[0]
                        except FileNotFoundError:
                            reg_path = None
                        task_path = tree_map.get(guid_u) or reg_path or guid_u

                        dyn = {}
                        try:
                            dyn = registry_binary_parser.parse_taskcache_dynamic_info(
                                winreg.QueryValueEx(task_key, "DynamicInfo")[0])
                        except FileNotFoundError:
                            pass

                        acts = {}
                        try:
                            acts = registry_binary_parser.parse_taskcache_actions(
                                winreg.QueryValueEx(task_key, "Actions")[0])
                        except FileNotFoundError:
                            pass

                        first = (acts.get("actions") or [{}])[0]
                        command = first.get("command", "")
                        arguments = first.get("arguments", "")
                        stamp = format_forensic_timestamp(get_current_utc())

                        cursor.execute(
                            '''INSERT OR REPLACE INTO ScheduledTasks
                               (task_path, task_guid, command, arguments, working_dir,
                                run_context, triggers_index, task_registered, last_run,
                                last_completed, last_result, parsed_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                            (task_path, guid_u, command, arguments,
                             first.get("working_dir", ""), acts.get("context", ""),
                             ",".join(trigger_map.get(guid_u, [])),
                             dyn.get("task_registered"), dyn.get("last_run"),
                             dyn.get("last_completed"), dyn.get("last_result"), stamp))

                        # Reuse, do not duplicate: a scheduled task IS an autostart
                        # entry, so it belongs in the same table the Run keys use.
                        if command:
                            full = (command + " " + arguments).strip() if arguments else command
                            cursor.execute(
                                '''INSERT OR IGNORE INTO AutoStartPrograms
                                   (location, program_name, command, record_state, parsed_at)
                                   VALUES (?, ?, ?, ?, ?)''',
                                ("TaskCache" + task_path,
                                 task_path.rsplit("\\", 1)[-1], full, LIVE_STATE, stamp))
                        task_count += 1

            print(f"Scheduled Tasks collected successfully. Total tasks: {task_count}")

        except Exception as e:
            logging.error(f"Error collecting Scheduled Tasks: {e}")
            print(f"Warning: Could not collect Scheduled Tasks data: {e}")

        # ------------------------------------------------------------------
        # Persistence keys (ASEP - auto-start extensibility points)
        #
        # Two layers, matching the rest of this parser: one raw table per key
        # holding every value verbatim, plus a roll-up row in AutoStartPrograms
        # so a single persistence query sees these beside Run and TaskCache.
        #
        # Read with KEY_WOW64_64KEY. Without it a 32-bit interpreter is
        # silently redirected into WOW6432Node and reports the wrong subtree -
        # no error, just the other half of the registry.
        # ------------------------------------------------------------------
        try:
            RD64 = winreg.KEY_READ | winreg.KEY_WOW64_64KEY

            for _t in ("winlogon", "image_file_execution_options", "appinit_dlls",
                       "appcert_dlls", "active_setup", "run_services",
                       "run_services_once", "policies_explorer_run",
                       "user_shell_folders", "lsa_packages", "boot_execute",
                       "clsid_inprocserver32",
                       # Tables are named for the artifact, not for the technique
                       # that abuses it: shell_open_command, not "uac_bypass".
                       # The row says what the registry holds; deciding whether
                       # it is an attack is the analyst's job, not the schema's.
                       "command_processor", "drivers32",
                       "shell_service_object_delay_load", "browser_helper_objects",
                       "shared_task_scheduler", "shell_icon_overlay_identifiers",
                       "credential_providers", "netsh_helper_dlls",
                       "amsi_providers", "security_providers",
                       "print_monitors", "print_processors", "network_providers",
                       "wmi_autorecover_mofs", "windows_load_run",
                       "shell_open_command"):
                cursor.execute(
                    f'CREATE TABLE IF NOT EXISTS {_t} ('
                    'hive TEXT, key_path TEXT, name TEXT, data TEXT, '
                    'data_decoded TEXT, type TEXT, '
                    'user_name TEXT, parsed_at TEXT)')
                # Additive migration: a case written by an earlier build
                # has these tables without data_decoded, and
                # CREATE TABLE IF NOT EXISTS is a no-op there.
                cursor.execute(f'PRAGMA table_info({_t})')
                if 'data_decoded' not in [c[1] for c in cursor.fetchall()]:
                    cursor.execute(
                        f'ALTER TABLE {_t} ADD COLUMN data_decoded TEXT')

            def _type_name(t):
                return {winreg.REG_SZ: "REG_SZ", winreg.REG_EXPAND_SZ: "REG_EXPAND_SZ",
                        winreg.REG_MULTI_SZ: "REG_MULTI_SZ", winreg.REG_DWORD: "REG_DWORD",
                        winreg.REG_QWORD: "REG_QWORD", winreg.REG_BINARY: "REG_BINARY",
                        winreg.REG_NONE: "REG_NONE"}.get(t, f"REG_TYPE_{t}")

            def _fmt(data):
                # REG_MULTI_SZ arrives as a Python list. Storing repr() would put
                # "['msv1_0', 'SshdPinAuthLsa']" in the cell; join it instead so the
                # column stays greppable. reg.exe shows the same value NUL-separated.
                #
                # Trailing empties are the NUL terminator, not data. winreg drops
                # them and python-registry keeps them, so without this the same
                # value reads "autocheck autochk *" live and
                # "autocheck autochk *; ; " offline.
                if isinstance(data, list):
                    items = [str(x) for x in data]
                    while items and items[-1] == "":
                        items.pop()
                    return "; ".join(items)
                return str(data)

            def _read_key(root, path, names=None):
                """[(name, data, type)] for a key, or None when the key is absent.

                Absent and present-but-empty are different facts: the first means
                the ASEP does not exist on this system, the second means it exists
                and is unused. Callers record only what actually exists.
                """
                out = []
                try:
                    with winreg.OpenKey(root, path, 0, RD64) as k:
                        if names:
                            # Enumerate and match case-insensitively rather than
                            # QueryValueEx by name, so the STORED name is what
                            # gets recorded. QueryValueEx is case-insensitive and
                            # returns the value whatever case you ask in, and the
                            # old code then wrote the name it had asked for -
                            # Winlogon really stores "VMApplet" and the case
                            # database ended up holding "VmApplet", a name that
                            # exists nowhere in the registry and does not match
                            # what the offline parser reads from the same key.
                            wanted = {str(n).lower(): n for n in names}
                            for i in range(winreg.QueryInfoKey(k)[1]):
                                try:
                                    n, d, t = winreg.EnumValue(k, i)
                                except OSError:
                                    continue
                                if (n or '').lower() in wanted:
                                    out.append((n, d, t))
                        else:
                            for i in range(winreg.QueryInfoKey(k)[1]):
                                try:
                                    n, d, t = winreg.EnumValue(k, i)
                                    out.append((n if n else "(Default)", d, t))
                                except OSError:
                                    pass
                except (FileNotFoundError, PermissionError, OSError):
                    return None
                return out

            def _subkeys(root, path):
                try:
                    with winreg.OpenKey(root, path, 0, RD64) as k:
                        return [winreg.EnumKey(k, i)
                                for i in range(winreg.QueryInfoKey(k)[0])]
                except (FileNotFoundError, PermissionError, OSError):
                    return []

            def _clsid_dll(clsid):
                """Server path behind a CLSID, or "" - for tables that store a GUID.

                Ask for the default value by name. Enumerating and taking the
                first entry looks equivalent and is not: InprocServer32 usually
                lists ThreadingModel first, so index 0 yields "Apartment" instead
                of a path - a plausible-looking value, not an error.

                Falls back through the 32-bit view and HKCU because per-user
                installs (OneDrive's shell overlays) register nowhere else.
                """
                for _r, _b in ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Classes\CLSID"),
                               (winreg.HKEY_LOCAL_MACHINE,
                                r"SOFTWARE\Classes\Wow6432Node\CLSID"),
                               (winreg.HKEY_LOCAL_MACHINE,
                                r"SOFTWARE\WOW6432Node\Classes\CLSID"),
                               (winreg.HKEY_CURRENT_USER, r"Software\Classes\CLSID")):
                    for _srv in ("InprocServer32", "LocalServer32"):
                        got = _read_key(_r, rf"{_b}\{clsid}\{_srv}", [""])
                        if got and got[0][1]:
                            return _fmt(got[0][1])
                return ""

            persist_stamp = format_forensic_timestamp(get_current_utc())
            asep_count = 0

            # %USERPROFILE% is per-account, so it cannot go in the shared
            # environment: expanding another user's row with the parsing
            # account's profile would name the wrong directory as evidence.
            # _record adds it per row, from the profile that row belongs to.
            _profile_paths = {}
            try:
                for _sid, _pp in (user_identity._profile_list_live() or {}).items():
                    _nm = get_username_from_sid(_sid)
                    if _nm and _pp:
                        _profile_paths[str(_nm).lower()] = str(_pp)
            except Exception as _pp_exc:
                logging.debug("profile paths for expansion: %s", _pp_exc)

            # HKCU-sourced rows are attributed to the account this parser is
            # running as. Reuses the existing SID -> name helpers rather than
            # re-deriving the username.
            _cu_sid = get_current_user_sid()
            current_username = get_username_from_sid(_cu_sid) if _cu_sid else None

            def _record(table, hive, key_path, name, data, rtype,
                        user_name=None, roll_up=None):
                """Write the raw row, and optionally the AutoStartPrograms roll-up."""
                nonlocal asep_count
                value = _fmt(data)
                # Guard the insert the way the rest of this parser does. These
                # tables have no PRIMARY KEY or UNIQUE constraint and nothing
                # clears them, so an unguarded INSERT appends the whole artifact
                # again every time a case is re-parsed - silently, and only
                # visible as a row count that keeps growing.
                if not check_exists(cursor, table,
                                    ['hive', 'key_path', 'name'],
                                    (hive, key_path, name)):
                    # A machine-wide key has no user to attribute, and a blank
                    # cell reads as attribution having failed. Label it instead,
                    # so "no user applies" and "we could not resolve one" cannot
                    # be mistaken for each other.
                    _owner = user_name or user_identity.MACHINE_WIDE_LABEL
                    # One decoder for every artifact - see
                    # render_registry_value. These 27 tables share this
                    # writer, so a locale, a switch or an unexpanded
                    # %VARIABLE% is read back the same way in all of
                    # them without a rule per table.
                    _row_env = _evidence_env
                    _prof = _profile_paths.get(str(user_name or "").lower())
                    if _prof:
                        _row_env = dict(_evidence_env, USERPROFILE=_prof)
                    _decoded = registry_binary_parser.render_registry_value(
                        table, name, data, rtype, _row_env)
                    if _decoded == value:
                        _decoded = ''      # a copy is not a decode
                    cursor.execute(
                        f'INSERT INTO {table} (hive, key_path, name, data, '
                        'data_decoded, type, user_name, parsed_at) '
                        'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                        (hive, key_path, name, value, _decoded,
                         _type_name(rtype), _owner, persist_stamp))
                    asep_count += 1
                if roll_up and value:
                    loc = roll_up if not user_name else f"HKU\\{user_name} {roll_up}"
                    if not check_exists(cursor, 'AutoStartPrograms',
                                        ['location', 'program_name'], (loc, name)):
                        cursor.execute(
                            'INSERT INTO AutoStartPrograms '
                            '(location, program_name, command, key_path, '
                            'record_state, parsed_at) '
                            'VALUES (?, ?, ?, ?, ?, ?)',
                            (loc, name, value, key_path, LIVE_STATE, persist_stamp))

            HKLM_R = winreg.HKEY_LOCAL_MACHINE

            # 1. Winlogon - Shell and Userinit are what actually launch the desktop.
            WL = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"
            for nm, dt, ty in (_read_key(HKLM_R, WL,
                    ["Shell", "Userinit", "Taskman", "AppSetup", "VmApplet",
                     "GinaDLL", "System", "AutoAdminLogon", "DefaultUserName"]) or []):
                _record("winlogon", "HKLM", WL, nm, dt, ty,
                        roll_up="HKLM Winlogon" if nm in ("Shell", "Userinit", "Taskman",
                                                          "GinaDLL", "AppSetup") else None)
            for sub in _subkeys(HKLM_R, WL + r"\Notify"):
                for nm, dt, ty in (_read_key(HKLM_R, f"{WL}\\Notify\\{sub}",
                                             ["DllName", "Logon", "Startup"]) or []):
                    _record("winlogon", "HKLM", f"{WL}\\Notify\\{sub}", nm, dt, ty,
                            roll_up="HKLM Winlogon\\Notify" if nm == "DllName" else None)

            # 2. IFEO. 80+ subkeys exist on a stock system and almost all are
            # benign flag containers, so record only entries that actually
            # redirect or monitor execution - otherwise this is 80 rows of noise.
            IFEO = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options"
            for sub in _subkeys(HKLM_R, IFEO):
                if sub.lower() == "silentprocessexit":
                    continue
                for nm, dt, ty in (_read_key(HKLM_R, f"{IFEO}\\{sub}",
                                             ["Debugger", "GlobalFlag", "VerifierDlls"]) or []):
                    _record("image_file_execution_options", "HKLM", f"{IFEO}\\{sub}",
                            f"{sub}!{nm}", dt, ty,
                            roll_up="HKLM IFEO\\Debugger" if nm == "Debugger" else None)
            for sub in _subkeys(HKLM_R, IFEO + r"\SilentProcessExit"):
                for nm, dt, ty in (_read_key(HKLM_R, f"{IFEO}\\SilentProcessExit\\{sub}",
                                             ["MonitorProcess", "ReportingMode"]) or []):
                    _record("image_file_execution_options", "HKLM",
                            f"{IFEO}\\SilentProcessExit\\{sub}", f"{sub}!{nm}", dt, ty,
                            roll_up="HKLM SilentProcessExit" if nm == "MonitorProcess" else None)

            # 3. AppInit_DLLs - loaded into every process linking user32.dll.
            for label, p in (("HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Windows"),
                             ("HKLM32", r"SOFTWARE\WOW6432Node\Microsoft\Windows NT\CurrentVersion\Windows")):
                for nm, dt, ty in (_read_key(HKLM_R, p,
                        ["AppInit_DLLs", "LoadAppInit_DLLs", "RequireSignedAppInit_DLLs"]) or []):
                    _record("appinit_dlls", label, p, nm, dt, ty,
                            roll_up=f"{label} AppInit_DLLs" if nm == "AppInit_DLLs" else None)

            # 4. AppCertDlls - absent on a stock system; its presence is the signal.
            ACD = r"SYSTEM\CurrentControlSet\Control\Session Manager\AppCertDlls"
            for nm, dt, ty in (_read_key(HKLM_R, ACD) or []):
                _record("appcert_dlls", "HKLM", ACD, nm, dt, ty, roll_up="HKLM AppCertDlls")

            # 5. Active Setup - StubPath runs once per user at first logon.
            for label, base in (("HKLM", r"SOFTWARE\Microsoft\Active Setup\Installed Components"),
                                ("HKLM32", r"SOFTWARE\WOW6432Node\Microsoft\Active Setup\Installed Components")):
                for comp in _subkeys(HKLM_R, base):
                    for nm, dt, ty in (_read_key(HKLM_R, f"{base}\\{comp}",
                                                 ["StubPath", "Version", "IsInstalled"]) or []):
                        _record("active_setup", label, f"{base}\\{comp}",
                                f"{comp}!{nm}", dt, ty,
                                roll_up=f"{label} Active Setup" if nm == "StubPath" else None)

            # 6/7/8. Legacy and policy autostart locations. Absent on modern
            # Windows, which is exactly why an attacker-created one stands out.
            for table, key, roll in (
                    ("run_services", r"SOFTWARE\Microsoft\Windows\CurrentVersion\RunServices", "RunServices"),
                    ("run_services_once", r"SOFTWARE\Microsoft\Windows\CurrentVersion\RunServicesOnce", "RunServicesOnce"),
                    ("policies_explorer_run", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Explorer\Run", "Policies\\Explorer\\Run")):
                for nm, dt, ty in (_read_key(HKLM_R, key) or []):
                    _record(table, "HKLM", key, nm, dt, ty, roll_up=f"HKLM {roll}")

            USF = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
            for nm, dt, ty in (_read_key(HKLM_R, USF, ["Common Startup", "Startup"]) or []):
                _record("user_shell_folders", "HKLM", USF, nm, dt, ty,
                        roll_up="HKLM User Shell Folders")

            # 9. LSA packages - DLLs loaded by lsass. REG_MULTI_SZ.
            LSA = r"SYSTEM\CurrentControlSet\Control\Lsa"
            for nm, dt, ty in (_read_key(HKLM_R, LSA,
                    ["Notification Packages", "Security Packages",
                     "Authentication Packages"]) or []):
                _record("lsa_packages", "HKLM", LSA, nm, dt, ty, roll_up="HKLM Lsa")

            # 10. Session Manager execute lists - run before any user logs on.
            SM = r"SYSTEM\CurrentControlSet\Control\Session Manager"
            for nm, dt, ty in (_read_key(HKLM_R, SM,
                    ["BootExecute", "SetupExecute", "Execute", "S0InitialCommand"]) or []):
                _record("boot_execute", "HKLM", SM, nm, dt, ty, roll_up="HKLM Session Manager")

            # 11. Per-user CLSID InprocServer32 shadowing the machine-wide entry,
            # so a user-writable DLL loads in place of the real component. Only
            # entries that actually shadow an HKLM CLSID are recorded - HKCU-only
            # CLSIDs are ordinary per-user registrations.
            CU_CLSID = r"Software\Classes\CLSID"
            for clsid in _subkeys(winreg.HKEY_CURRENT_USER, CU_CLSID):
                user_vals = _read_key(winreg.HKEY_CURRENT_USER,
                                      f"{CU_CLSID}\\{clsid}\\InprocServer32")
                if not user_vals:
                    continue
                if _read_key(HKLM_R, rf"SOFTWARE\Classes\CLSID\{clsid}\InprocServer32") is None:
                    continue                      # no machine-wide entry to shadow
                for nm, dt, ty in user_vals:
                    _record("clsid_inprocserver32", "HKCU",
                            f"{CU_CLSID}\\{clsid}\\InprocServer32",
                            f"{clsid}!{nm}", dt, ty,
                            user_name=current_username,
                            roll_up="COM InprocServer32" if nm == "(Default)" else None)

            # 12. Command Processor AutoRun - runs on every cmd.exe launch. The
            # HKCU copy is the one that matters: it needs no admin rights, and on
            # a developer box a legitimate one (clink, chocolatey) is common, so
            # record both hives and let the analyst compare.
            for _hv, _root, _cp in (("HKLM", HKLM_R, r"SOFTWARE\Microsoft\Command Processor"),
                                    ("HKCU", winreg.HKEY_CURRENT_USER,
                                     r"Software\Microsoft\Command Processor")):
                for nm, dt, ty in (_read_key(_root, _cp,
                        ["AutoRun", "DefaultColor", "CompletionChar"]) or []):
                    _record("command_processor", _hv, _cp, nm, dt, ty,
                            user_name=current_username if _hv == "HKCU" else None,
                            roll_up=f"{_hv} Command Processor" if nm == "AutoRun" else None)

            # 13. Drivers32 - multimedia driver DLLs loaded by winmm. Stock values
            # are the wdmaud/msacm set; an added entry is a load point.
            D32 = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Drivers32"
            for _hv, _p in (("HKLM", D32),
                            ("HKLM32", r"SOFTWARE\WOW6432Node\Microsoft\Windows NT"
                                       r"\CurrentVersion\Drivers32")):
                for nm, dt, ty in (_read_key(HKLM_R, _p) or []):
                    _record("drivers32", _hv, _p, nm, dt, ty,
                            roll_up=f"{_hv} Drivers32")

            # 14. ShellServiceObjectDelayLoad - COM objects Explorer loads at
            # startup. Stock content is WebCheck only.
            SSODL = r"SOFTWARE\Microsoft\Windows\CurrentVersion\ShellServiceObjectDelayLoad"
            for nm, dt, ty in (_read_key(HKLM_R, SSODL) or []):
                _record("shell_service_object_delay_load", "HKLM", SSODL, nm, dt, ty,
                        roll_up="HKLM SSODL")

            # 15. Browser Helper Objects - loaded into Internet Explorer / the
            # legacy WebBrowser control. Each subkey is a CLSID; resolve it to the
            # backing DLL so the row names a file rather than a GUID.
            for _hv, _bho in (("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion"
                                       r"\Explorer\Browser Helper Objects"),
                              ("HKLM32", r"SOFTWARE\WOW6432Node\Microsoft\Windows"
                                         r"\CurrentVersion\Explorer\Browser Helper Objects")):
                for clsid in _subkeys(HKLM_R, _bho):
                    _record("browser_helper_objects", _hv, f"{_bho}\\{clsid}",
                            clsid, _clsid_dll(clsid), winreg.REG_SZ,
                            roll_up=f"{_hv} Browser Helper Objects")

            # 16. SharedTaskScheduler - absent on modern Windows, which is the
            # whole point: an entry here is not a leftover, it was put there.
            STS = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\SharedTaskScheduler"
            for nm, dt, ty in (_read_key(HKLM_R, STS) or []):
                _record("shared_task_scheduler", "HKLM", STS, nm, dt, ty,
                        roll_up="HKLM SharedTaskScheduler")

            # 17. Shell icon overlay handlers - in-process DLLs loaded by Explorer.
            # OneDrive/cloud providers legitimately register several.
            SIOI = (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer"
                    r"\ShellIconOverlayIdentifiers")
            for sub in _subkeys(HKLM_R, SIOI):
                for nm, dt, ty in (_read_key(HKLM_R, f"{SIOI}\\{sub}", [""]) or []):
                    _clsid = _fmt(dt)
                    _dll = _clsid_dll(_clsid)
                    _record("shell_icon_overlay_identifiers", "HKLM",
                            f"{SIOI}\\{sub}", sub,
                            f"{_clsid} -> {_dll}" if _dll else _clsid, ty,
                            roll_up="HKLM ShellIconOverlayIdentifiers")

            # 18. Credential providers - DLLs in the logon UI. A rogue one sees
            # every credential typed at the lock screen. ~21 ship with Windows,
            # so the DLL path matters more than the count.
            for _lbl, _cpk in (
                    ("Credential Providers",
                     r"SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication"
                     r"\Credential Providers"),
                    ("Credential Provider Filters",
                     r"SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication"
                     r"\Credential Provider Filters")):
                for clsid in _subkeys(HKLM_R, _cpk):
                    _dll = _clsid_dll(clsid)
                    _name = _read_key(HKLM_R, f"{_cpk}\\{clsid}", [""])
                    _record("credential_providers", "HKLM", f"{_cpk}\\{clsid}",
                            f"{_lbl}!{clsid}",
                            f"{_fmt(_name[0][1]) if _name else ''} "
                            f"[{_dll or 'no registered server'}]",
                            winreg.REG_SZ, roll_up="HKLM Credential Providers")

            # 19. Netsh helper DLLs - loaded every time netsh.exe runs.
            NETSH = r"SOFTWARE\Microsoft\Netsh"
            for nm, dt, ty in (_read_key(HKLM_R, NETSH) or []):
                _record("netsh_helper_dlls", "HKLM", NETSH, nm, dt, ty,
                        roll_up="HKLM Netsh")

            # 20. AMSI providers - a hostile provider registered here sees, and
            # can lie about, every script AMSI scans.
            AMSI = r"SOFTWARE\Microsoft\AMSI\Providers"
            for clsid in _subkeys(HKLM_R, AMSI):
                _dll = _read_key(HKLM_R,
                                 rf"SOFTWARE\Classes\CLSID\{clsid}\InprocServer32")
                _record("amsi_providers", "HKLM", f"{AMSI}\\{clsid}", clsid,
                        _fmt(_dll[0][1]) if _dll else "", winreg.REG_SZ,
                        roll_up="HKLM AMSI Providers")

            # 21. Security Support Providers - DLLs loaded into lsass at boot.
            # Stock is credssp.dll. Distinct from lsa_packages above: this is the
            # SecurityProviders value, not the Lsa package lists.
            SSP = r"SYSTEM\CurrentControlSet\Control\SecurityProviders"
            for nm, dt, ty in (_read_key(HKLM_R, SSP, ["SecurityProviders"]) or []):
                _record("security_providers", "HKLM", SSP, nm, dt, ty,
                        roll_up="HKLM SecurityProviders")

            # 22. Print monitors - DLLs loaded by spoolsv.exe as SYSTEM.
            PMON = r"SYSTEM\CurrentControlSet\Control\Print\Monitors"
            for sub in _subkeys(HKLM_R, PMON):
                for nm, dt, ty in (_read_key(HKLM_R, f"{PMON}\\{sub}", ["Driver"]) or []):
                    _record("print_monitors", "HKLM", f"{PMON}\\{sub}",
                            f"{sub}!{nm}", dt, ty, roll_up="HKLM Print Monitors")

            # 23. Print processors - same spooler load point, one level deeper
            # under each print environment.
            PENV = r"SYSTEM\CurrentControlSet\Control\Print\Environments"
            for env in _subkeys(HKLM_R, PENV):
                _pp = f"{PENV}\\{env}\\Print Processors"
                for proc in _subkeys(HKLM_R, _pp):
                    for nm, dt, ty in (_read_key(HKLM_R, f"{_pp}\\{proc}",
                                                 ["Driver"]) or []):
                        _record("print_processors", "HKLM", f"{_pp}\\{proc}",
                                f"{env}\\{proc}!{nm}", dt, ty,
                                roll_up="HKLM Print Processors")

            # 24. Network providers - ProviderOrder names the services whose
            # DLLs handle UNC paths. Stock is RDPNP,LanmanWorkstation,webclient
            # plus OS extras; an inserted name loads first.
            NPO = r"SYSTEM\CurrentControlSet\Control\NetworkProvider\Order"
            for nm, dt, ty in (_read_key(HKLM_R, NPO, ["ProviderOrder"]) or []):
                _record("network_providers", "HKLM", NPO, nm, dt, ty,
                        roll_up="HKLM NetworkProvider Order")
                for _svc in _fmt(dt).split(","):
                    _svc = _svc.strip()
                    if not _svc:
                        continue
                    _pp = rf"SYSTEM\CurrentControlSet\Services\{_svc}\NetworkProvider"
                    for _n2, _d2, _t2 in (_read_key(HKLM_R, _pp,
                                                    ["ProviderPath", "Name"]) or []):
                        _record("network_providers", "HKLM", _pp,
                                f"{_svc}!{_n2}", _d2, _t2)

            # 25. WMI autorecover MOFs - MOF files recompiled into the WMI
            # repository when it rebuilds, a durable persistence path.
            CIMOM = r"SOFTWARE\Microsoft\WBEM\CIMOM"
            for nm, dt, ty in (_read_key(HKLM_R, CIMOM,
                    ["Autorecover MOFs", "Autorecover MOFs timestamp"]) or []):
                _record("wmi_autorecover_mofs", "HKLM", CIMOM, nm, dt, ty,
                        roll_up="HKLM WMI Autorecover MOFs"
                                if nm == "Autorecover MOFs" else None)

            # 26. Per-user Load and Run - the NT-era pair under the user's own
            # Windows key. Empty on a stock profile.
            UWIN = r"Software\Microsoft\Windows NT\CurrentVersion\Windows"
            for nm, dt, ty in (_read_key(winreg.HKEY_CURRENT_USER, UWIN,
                                         ["Load", "Run"]) or []):
                _record("windows_load_run", "HKCU", UWIN, nm, dt, ty,
                        user_name=current_username, roll_up="HKCU Windows Load/Run")

            # 27. shell\open\command for the ProgIDs used by the well-known UAC
            # bypasses. HKCU wins over HKLM for the same ProgID, so an HKCU row
            # here means the machine-wide handler is being overridden. Recorded
            # as the artifact it is - the analyst decides whether it is abuse.
            # DelegateExecute is included deliberately: the fodhelper technique
            # works by adding (Default) and blanking DelegateExecute.
            for _progid in ("exefile", "ms-settings", "mscfile", "Folder",
                            "txtfile", "batfile", "cmdfile", "regfile"):
                for _hv, _root, _pfx in (("HKLM", HKLM_R, "SOFTWARE\\Classes"),
                                         ("HKCU", winreg.HKEY_CURRENT_USER,
                                          "Software\\Classes")):
                    _soc = rf"{_pfx}\{_progid}\shell\open\command"
                    for nm, dt, ty in (_read_key(_root, _soc) or []):
                        _record("shell_open_command", _hv, _soc,
                                f"{_progid}!{nm}", dt, ty,
                                user_name=current_username if _hv == "HKCU" else None,
                                roll_up=f"{_hv} shell\\open\\command"
                                        if _hv == "HKCU" else None)

            conn.commit()
            print(f"Persistence keys collected successfully. Total values: {asep_count}")

        except Exception as e:
            logging.error(f"Error collecting persistence keys: {e}")
            print(f"Warning: Could not collect persistence key data: {e}")
        # ------------------------------------------------------------------
        # Forensic coverage: security posture, network exposure, devices,
        # per-user activity and application artifacts.
        #
        # SecurityPosture stays a shared name/value/meaning table for settings
        # that are only ever read as a set. Everything an examiner queries by
        # name gets its own table, named for the artifact and not for the
        # technique that abuses it - rdp_tcp, not "rdp_backdoor".
        # ------------------------------------------------------------------
        try:
            RD64 = winreg.KEY_READ | winreg.KEY_WOW64_64KEY
            HKLM_R = winreg.HKEY_LOCAL_MACHINE
            HKCU_R = winreg.HKEY_CURRENT_USER
            cov_stamp = format_forensic_timestamp(get_current_utc())

            def _cv(root, path, name):
                """(value, present) for a single value."""
                try:
                    with winreg.OpenKey(root, path, 0, RD64) as k:
                        return winreg.QueryValueEx(k, name)[0], True
                except (FileNotFoundError, PermissionError, OSError):
                    return None, False

            def _cvals(root, path):
                out = []
                try:
                    with winreg.OpenKey(root, path, 0, RD64) as k:
                        for i in range(winreg.QueryInfoKey(k)[1]):
                            try:
                                n, d, t = winreg.EnumValue(k, i)
                                out.append((n if n else "(Default)", d, t))
                            except OSError:
                                pass
                except (FileNotFoundError, PermissionError, OSError):
                    return []
                return out

            def _csubs(root, path):
                try:
                    with winreg.OpenKey(root, path, 0, RD64) as k:
                        return [winreg.EnumKey(k, i)
                                for i in range(winreg.QueryInfoKey(k)[0])]
                except (FileNotFoundError, PermissionError, OSError):
                    return []

            cov_counts = {}

            def _ins(table, cols, values, key_cols):
                """Guarded insert - re-parsing a case must not duplicate rows."""
                key_vals = tuple(values[cols.index(c)] for c in key_cols)
                if check_exists(cursor, table, list(key_cols), key_vals):
                    return
                cursor.execute(
                    'INSERT INTO %s (%s) VALUES (%s)'
                    % (table, ", ".join(cols), ", ".join("?" * len(cols))), values)
                cov_counts[table] = cov_counts.get(table, 0) + 1

            # Additive migration for the coverage tables that gained
            # value_decoded. CREATE TABLE IF NOT EXISTS is a no-op on a
            # case an earlier build wrote, so the column has to be added
            # explicitly or the insert below fails on it.
            for _cov_t in (
                    "explorer_advanced", "rdp_tcp", "windows_script_host",
                    "system_environment", "dnscache_parameters"):
                try:
                    cursor.execute('PRAGMA table_info(%s)' % _cov_t)
                    if 'value_decoded' not in [c[1] for c in cursor.fetchall()]:
                        cursor.execute(
                            'ALTER TABLE %s ADD COLUMN value_decoded TEXT'
                            % _cov_t)
                except sqlite3.Error as _cov_mig:
                    logging.debug('value_decoded migration %s: %s',
                                  _cov_t, _cov_mig)

            def _cov_dec(table, name, data, vtype=None):
                """The decoded form of a coverage value, or "".

                Same decoder as every other table - see
                render_registry_value. A result equal to the raw value
                is discarded: a copy is not a decode, which is the
                defect this column exists to avoid repeating.
                """
                try:
                    got = registry_binary_parser.render_registry_value(
                        table, name, data, vtype, _evidence_env) or ''
                except Exception:
                    return ''
                return '' if got == str(data) else got

            # ---------------------------------------------------------- posture
            cursor.execute('''CREATE TABLE IF NOT EXISTS SecurityPosture (
                setting TEXT, value_raw TEXT, value_decoded TEXT,
                default_value TEXT, assessment TEXT, meaning TEXT,
                key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''')

            def _dec_lastaccess(v):
                # 0x80000000 marks "system managed"; the low bits are the mode.
                # 0/2 = last-access updates ENABLED, 1/3 = DISABLED. fsutil
                # reports the same pair, and getting this backwards inverts a
                # conclusion about whether $STANDARD_INFORMATION times are live.
                try:
                    n = int(v)
                except (TypeError, ValueError):
                    return "unknown", "informational"
                managed = "system-managed" if n & 0x80000000 else "user-set"
                mode = n & 0xF
                on = mode in (0, 2)
                return ("%s, last-access updates %s"
                        % (managed, "ENABLED" if on else "DISABLED"),
                        "informational")

            def _dec_flag(v, present, bad_value, weak_msg, ok_msg):
                if not present:
                    return "absent (Windows default)", "default", ok_msg
                if str(v) == str(bad_value):
                    return str(v), "weakened", weak_msg
                return str(v), "default", ok_msg

            POSTURE = [
                (HKLM_R, r"SYSTEM\CurrentControlSet\Control\SecurityProviders\WDigest",
                 "UseLogonCredential", 1, "0 / absent",
                 "1 caches plaintext credentials in LSASS memory",
                 "credentials not cached in plaintext"),
                (HKLM_R, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System",
                 "EnableLUA", 0, "1", "0 disables UAC entirely", "UAC enabled"),
                (HKLM_R, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System",
                 "LocalAccountTokenFilterPolicy", 1, "0 / absent",
                 "1 allows remote admin with local accounts (lateral movement)",
                 "remote local-account admin restricted"),
                (HKLM_R, r"SYSTEM\CurrentControlSet\Control\Terminal Server",
                 "fDenyTSConnections", 0, "1", "0 means RDP is accepting connections",
                 "RDP disabled"),
                (HKLM_R, r"SOFTWARE\Policies\Microsoft\Windows Defender",
                 "DisableAntiSpyware", 1, "0 / absent", "1 disables Defender",
                 "Defender not disabled by policy"),
                (HKLM_R, r"SOFTWARE\Policies\Microsoft\Windows Defender\Real-Time Protection",
                 "DisableRealtimeMonitoring", 1, "0 / absent",
                 "1 disables real-time protection", "real-time protection not disabled"),
                (HKLM_R, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\SystemRestore",
                 "DisableSR", 1, "0 / absent",
                 "1 disables restore points, removing a recovery source",
                 "system restore not disabled"),
            ]
            for root, path, name, bad, dflt, weak, okmsg in POSTURE:
                v, present = _cv(root, path, name)
                dec, assess, msg = _dec_flag(v, present, bad, weak, okmsg)
                _ins("SecurityPosture",
                     ["setting", "value_raw", "value_decoded", "default_value",
                      "assessment", "meaning", "key_path", "parsed_at"],
                     (name, "(absent)" if not present else str(v), dec, dflt,
                      assess, msg, path, cov_stamp),
                     ["setting", "key_path"])

            # Settings whose meaning is not a simple flag.
            v, present = _cv(HKLM_R, r"SYSTEM\CurrentControlSet\Control\FileSystem",
                             "NtfsDisableLastAccessUpdate")
            dec, assess = _dec_lastaccess(v) if present else ("absent", "default")
            _ins("SecurityPosture",
                 ["setting", "value_raw", "value_decoded", "default_value",
                  "assessment", "meaning", "key_path", "parsed_at"],
                 ("NtfsDisableLastAccessUpdate", "(absent)" if not present else str(v),
                  dec, "0x80000002 (system-managed, enabled)", assess,
                  "decides whether file last-access times are maintained",
                  r"SYSTEM\CurrentControlSet\Control\FileSystem", cov_stamp),
                 ["setting", "key_path"])

            v, present = _cv(HKLM_R, r"SYSTEM\CurrentControlSet\Control\Lsa", "RunAsPPL")
            _ins("SecurityPosture",
                 ["setting", "value_raw", "value_decoded", "default_value",
                  "assessment", "meaning", "key_path", "parsed_at"],
                 ("RunAsPPL", "(absent)" if not present else str(v),
                  {None: "absent", 0: "not protected", 1: "protected (UEFI lock)",
                   2: "protected (no UEFI lock)"}.get(v, str(v)),
                  "absent or 0",
                  "hardened" if present and v in (1, 2) else "default",
                  "LSASS run as a protected process resists credential dumping",
                  r"SYSTEM\CurrentControlSet\Control\Lsa", cov_stamp),
                 ["setting", "key_path"])

            for name, path, root in (
                    ("EnableScriptBlockLogging",
                     r"SOFTWARE\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging", HKLM_R),
                    ("EnableModuleLogging",
                     r"SOFTWARE\Policies\Microsoft\Windows\PowerShell\ModuleLogging", HKLM_R)):
                v, present = _cv(root, path, name)
                _ins("SecurityPosture",
                     ["setting", "value_raw", "value_decoded", "default_value",
                      "assessment", "meaning", "key_path", "parsed_at"],
                     (name, "(absent)" if not present else str(v),
                      "enabled" if present and v == 1 else "not enabled",
                      "absent (off by default)",
                      "hardened" if present and v == 1 else "default",
                      "PowerShell logging is off unless enabled - absence limits "
                      "what evidence exists, it is not tampering",
                      path, cov_stamp),
                     ["setting", "key_path"])

            # PendingFileRenameOperations: staged file replacement/deletion at reboot.
            v, present = _cv(HKLM_R, r"SYSTEM\CurrentControlSet\Control\Session Manager",
                             "PendingFileRenameOperations")
            if present and v:
                items = [x for x in (v if isinstance(v, list) else [str(v)]) if x]
                for i in range(0, len(items) - 1, 2):
                    src_f, dst_f = items[i], items[i + 1]
                    _ins("SecurityPosture",
                         ["setting", "value_raw", "value_decoded", "default_value",
                          "assessment", "meaning", "key_path", "parsed_at"],
                         ("PendingFileRenameOperations", src_f,
                          ("delete" if not dst_f else "rename to " + dst_f),
                          "absent", "informational",
                          "file operations queued for the next boot",
                          r"SYSTEM\CurrentControlSet\Control\Session Manager", cov_stamp),
                         ["setting", "value_raw"])

            # OS build and edition. ProductName still reads "Windows 10" on
            # Windows 11 - Microsoft froze it - so the build number is the truth.
            CV = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
            for _n, _why in (("ProductName", "frozen at 'Windows 10' on Win11 - trust the build"),
                             ("CurrentBuild", "22000+ means Windows 11"),
                             ("DisplayVersion", "feature update level"),
                             ("EditionID", "SKU"),
                             ("InstallDate", "OS install time, Unix epoch")):
                _v, _p = _cv(HKLM_R, CV, _n)
                if _p:
                    _ins("SecurityPosture",
                         ["setting", "value_raw", "value_decoded", "default_value",
                          "assessment", "meaning", "key_path", "parsed_at"],
                         (_n, str(_v), str(_v), "varies", "informational", _why,
                          CV, cov_stamp),
                         ["setting", "key_path"])

            # Proxy, SafeBoot and crash dump policy.
            for _root, _path, _n, _why in (
                    (HKCU_R, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                     "ProxyServer", "traffic routed through a proxy"),
                    (HKCU_R, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                     "ProxyEnable", "1 means the proxy above is in use"),
                    (HKLM_R, r"SYSTEM\CurrentControlSet\Control\CrashControl",
                     "CrashDumpEnabled", "0 none, 1 complete, 2 kernel, 3 small, 7 automatic"),
                    (HKLM_R, r"SYSTEM\CurrentControlSet\Control\CrashControl",
                     "DumpFile", "where a crash dump would be written")):
                _v, _p = _cv(_root, _path, _n)
                _ins("SecurityPosture",
                     ["setting", "value_raw", "value_decoded", "default_value",
                      "assessment", "meaning", "key_path", "parsed_at"],
                     (_n, "(absent)" if not _p else str(_v),
                      "(absent)" if not _p else str(_v), "varies", "informational",
                      _why, _path, cov_stamp),
                     ["setting", "key_path"])

            # PrefetchParameters. 0 means prefetch is off, so an absent
            # Prefetch directory is configuration rather than an anti-forensic
            # wipe - which is the whole reason to record it. The offline parser
            # has always read this; the live one never did.
            _PFP = (r"SYSTEM\CurrentControlSet\Control\Session Manager"
                    r"\Memory Management\PrefetchParameters")
            for _n, _why in (("EnablePrefetcher",
                              "0 off, 1 app, 2 boot, 3 both (default)"),
                             ("EnableSuperfetch", "SysMain/Superfetch state")):
                _v, _p = _cv(HKLM_R, _PFP, _n)
                if not _p:
                    continue
                _ins("SecurityPosture",
                     ["setting", "value_raw", "value_decoded", "default_value",
                      "assessment", "meaning", "key_path", "parsed_at"],
                     (_n, str(_v), str(_v), "3",
                      "weakened" if str(_v) == "0" else "informational",
                      _why, _PFP, cov_stamp),
                     ["setting", "key_path"])

            # SafeBoot: which services survive a safe-mode boot. Malware that adds
            # itself here keeps running when an analyst boots to safe mode.
            # r-strings cannot end in a backslash, so these paths are joined.
            BS = chr(92)
            for _which in ("Minimal", "Network"):
                _sb = "SYSTEM" + BS + "CurrentControlSet" + BS + "Control" + BS + "SafeBoot" + BS + _which
                _n_sb = len(_csubs(HKLM_R, _sb))
                _ins("SecurityPosture",
                     ["setting", "value_raw", "value_decoded", "default_value",
                      "assessment", "meaning", "key_path", "parsed_at"],
                     ("SafeBoot\\" + _which, str(_n_sb), "%d entries" % _n_sb,
                      "varies by Windows build", "informational",
                      "services and drivers that still start in safe mode",
                      _sb, cov_stamp),
                     ["setting", "key_path"])

            # ------------------------------------------------- defender exclusions
            cursor.execute('''CREATE TABLE IF NOT EXISTS DefenderExclusions (
                exclusion_type TEXT, value TEXT, source TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT,
                parsed_at TEXT)''')
            for base, src in ((r"SOFTWARE\Microsoft\Windows Defender\Exclusions", "local"),
                              (r"SOFTWARE\Policies\Microsoft\Windows Defender\Exclusions", "policy")):
                # Singular forms are mapped, not derived: rstrip("s") strips
                # every trailing 's' and turns "Processes" into "Processe".
                for kind, singular in (("Paths", "Path"), ("Extensions", "Extension"),
                                       ("Processes", "Process"),
                                       ("TemporaryPaths", "TemporaryPath")):
                    for vn, vd, vt in _cvals(HKLM_R, base + "\\" + kind):
                        _ins("DefenderExclusions",
                             ["exclusion_type", "value", "source", "key_path", "parsed_at"],
                             (singular, vn, src, base + "\\" + kind, cov_stamp),
                             ["exclusion_type", "value"])

            # --------------------------------------------------------- firewall
            cursor.execute('''CREATE TABLE IF NOT EXISTS FirewallRules (
                rule_type TEXT, rule_name TEXT, display_name TEXT, action TEXT,
                direction TEXT, enabled TEXT, protocol TEXT, local_port TEXT,
                remote_port TEXT, application TEXT, service TEXT, profile TEXT,
                key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''')
            FW = (r"SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters"
                  r"\FirewallPolicy\FirewallRules")
            for vn, vd, vt in _cvals(HKLM_R, FW):
                f = {}
                for part in str(vd).split("|"):
                    if "=" in part:
                        kk, _, vv = part.partition("=")
                        f.setdefault(kk, vv)
                _ins("FirewallRules",
                     ["rule_type", "rule_name", "display_name", "action", "direction",
                      "enabled", "protocol", "local_port", "remote_port", "application",
                      "service", "profile", "key_path", "parsed_at"],
                     ("FirewallRule", vn, f.get("Name", ""), f.get("Action", ""),
                      f.get("Dir", ""), f.get("Active", ""), f.get("Protocol", ""),
                      f.get("LPort", ""), f.get("RPort", ""), f.get("App", ""),
                      f.get("Svc", ""), f.get("Profile", ""), FW, cov_stamp),
                     ["rule_type", "rule_name"])
            for proto in ("v4tov4", "v4tov6", "v6tov4", "v6tov6"):
                for tp in ("tcp", "udp"):
                    pp = r"SYSTEM\CurrentControlSet\Services\PortProxy\%s\%s" % (proto, tp)
                    for vn, vd, vt in _cvals(HKLM_R, pp):
                        _ins("FirewallRules",
                             ["rule_type", "rule_name", "display_name", "action",
                              "direction", "enabled", "protocol", "local_port",
                              "remote_port", "application", "service", "profile",
                              "key_path", "parsed_at"],
                             ("PortProxy", vn, "%s -> %s" % (vn, vd), "Forward", "In",
                              "TRUE", tp.upper(), vn.split("/")[-1] if "/" in vn else vn,
                              str(vd), "", "", proto, pp, cov_stamp),
                             ["rule_type", "rule_name"])

            # ----------------------------------------------------------- shares
            cursor.execute('''CREATE TABLE IF NOT EXISTS NetworkShares (
                share_name TEXT, share_path TEXT, remark TEXT, raw TEXT,
                key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''')
            SH = r"SYSTEM\CurrentControlSet\Services\LanmanServer\Shares"
            for vn, vd, vt in _cvals(HKLM_R, SH):
                parts = vd if isinstance(vd, list) else [str(vd)]
                d = {}
                for p in parts:
                    if "=" in p:
                        kk, _, vv = p.partition("=")
                        d[kk] = vv
                _ins("NetworkShares",
                     ["share_name", "share_path", "remark", "raw", "key_path", "parsed_at"],
                     (vn, d.get("Path", ""), d.get("Remark", ""), "; ".join(parts),
                      SH, cov_stamp),
                     ["share_name"])

            # ------------------------------------------------------ devices
            cursor.execute('''CREATE TABLE IF NOT EXISTS ConnectedDevices (
                device_type TEXT, device_id TEXT, friendly_name TEXT, details TEXT,
                key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''')
            WPD = r"SOFTWARE\Microsoft\Windows Portable Devices\Devices"
            for s in _csubs(HKLM_R, WPD):
                fn, _p = _cv(HKLM_R, WPD + "\\" + s, "FriendlyName")
                _ins("ConnectedDevices",
                     ["device_type", "device_id", "friendly_name", "details",
                      "key_path", "parsed_at"],
                     ("PortableDevice", s, str(fn or ""), "", WPD, cov_stamp),
                     ["device_type", "device_id"])
            BT = r"SYSTEM\CurrentControlSet\Services\BTHPORT\Parameters\Devices"
            for s in _csubs(HKLM_R, BT):
                nm, _p = _cv(HKLM_R, BT + "\\" + s, "Name")
                if isinstance(nm, bytes):
                    nm = nm.split(b"\x00")[0].decode("utf-8", "ignore")
                _ins("ConnectedDevices",
                     ["device_type", "device_id", "friendly_name", "details",
                      "key_path", "parsed_at"],
                     ("Bluetooth", s, str(nm or ""), "MAC address as key name",
                      BT, cov_stamp),
                     ["device_type", "device_id"])
            EMD = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\EMDMgmt"
            for s in _csubs(HKLM_R, EMD):
                _ins("ConnectedDevices",
                     ["device_type", "device_id", "friendly_name", "details",
                      "key_path", "parsed_at"],
                     ("EMDMgmt", s, "", "volume serial and label history",
                      EMD, cov_stamp),
                     ["device_type", "device_id"])
            SCSI = r"SYSTEM\CurrentControlSet\Enum\SCSI"
            for s in _csubs(HKLM_R, SCSI):
                for inst in _csubs(HKLM_R, SCSI + "\\" + s):
                    fn, _p = _cv(HKLM_R, "%s\\%s\\%s" % (SCSI, s, inst), "FriendlyName")
                    _ins("ConnectedDevices",
                         ["device_type", "device_id", "friendly_name", "details",
                          "key_path", "parsed_at"],
                         ("SCSI", "%s\\%s" % (s, inst), str(fn or ""), "",
                          SCSI, cov_stamp),
                         ["device_type", "device_id"])
            PRN = r"SYSTEM\CurrentControlSet\Control\Print\Printers"
            for s in _csubs(HKLM_R, PRN):
                port, _p = _cv(HKLM_R, PRN + "\\" + s, "Port")
                _ins("ConnectedDevices",
                     ["device_type", "device_id", "friendly_name", "details",
                      "key_path", "parsed_at"],
                     ("Printer", s, s, "port: %s" % (port or ""), PRN, cov_stamp),
                     ["device_type", "device_id"])
            # The SOFTWARE copy of the same list. On a live machine this mostly
            # repeats the SYSTEM one, but it is the only copy that exists in a
            # hive file, so reading both keeps the two parsers on the same
            # evidence rather than on the same code path.
            PRN_SW = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Print\Printers"
            for s in _csubs(HKLM_R, PRN_SW):
                port, _p = _cv(HKLM_R, PRN_SW + "\\" + s, "Port")
                _ins("ConnectedDevices",
                     ["device_type", "device_id", "friendly_name", "details",
                      "key_path", "parsed_at"],
                     ("Printer", s, s, "port: %s" % (port or ""), PRN_SW, cov_stamp),
                     ["device_type", "device_id"])

            # ------------------------------------------------- per-user artifacts
            # Collected for EVERY loaded user, not just the account running
            # Crow-Eye. HKU\<SID>\... returns the same data HKCU does for the
            # current user, so one loop covers both.
            _cu_sid2 = get_current_user_sid()
            _cu_name = get_username_from_sid(_cu_sid2) if _cu_sid2 else None
            user_roots = [(HKCU_R, "", _cu_name or "current user")]
            try:
                # Every loaded hive, not only the S-1-5-21 accounts. .DEFAULT
                # is the profile that applies before anyone logs on and the
                # three service SIDs are what Windows itself runs as - all four
                # are places persistence hides, and all four were skipped. They
                # are labelled, not resolved, so a service account's row can
                # never be mistaken for a person's.
                with winreg.OpenKey(winreg.HKEY_USERS, "", 0, RD64) as _uk:
                    for _i in range(winreg.QueryInfoKey(_uk)[0]):
                        _s = winreg.EnumKey(_uk, _i)
                        if _s.endswith("_Classes") or _s == _cu_sid2:
                            continue
                        _sys_label = user_identity.system_account_label(_s)
                        if _sys_label:
                            user_roots.append((winreg.HKEY_USERS, _s + "\\", _sys_label))
                        elif _s.startswith("S-1-5-21"):
                            user_roots.append((winreg.HKEY_USERS, _s + "\\", _s))
            except OSError as e:
                logging.debug("HKEY_USERS walk for coverage: %s", e)

            cursor.execute('''CREATE TABLE IF NOT EXISTS MountPoints2 (
                user_name TEXT, mount_id TEXT, mount_type TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT,
                parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS RDPClientMRU (
                user_name TEXT, entry_type TEXT, server TEXT, username_hint TEXT,
                key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS OfficeDocuments (
                user_name TEXT, application TEXT, version TEXT, kind TEXT,
                document TEXT, raw TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS FeatureUsage (
                user_name TEXT, usage_type TEXT, program TEXT, count INTEGER,
                key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS CompatibilityAssistant (
                user_name TEXT, program_path TEXT, blob_size INTEGER,
                key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS RecentApps (
                user_name TEXT, app_id TEXT, app_path TEXT, launch_count INTEGER,
                last_accessed TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS ApplicationArtifacts (
                user_name TEXT, application TEXT, artifact TEXT, name TEXT,
                value TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS file_exts (
                user_name TEXT, extension TEXT, choice_type TEXT, progid TEXT,
                key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS cid_size_mru (
                user_name TEXT, position INTEGER, application TEXT,
                key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS programs_cache (
                user_name TEXT, value_name TEXT, blob_size INTEGER,
                key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS regedit_lastkey (
                user_name TEXT, name TEXT, value TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT,
                parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS printer_connections (
                user_name TEXT, connection TEXT, server TEXT, printer TEXT,
                key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS explorer_advanced (
                user_name TEXT, setting TEXT, value TEXT, value_decoded TEXT, default_value TEXT,
                meaning TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''')

            for _root, _pfx, _uname in user_roots:
                # MountPoints2 - volumes and network shares this user mounted.
                MP = _pfx + r"Software\Microsoft\Windows\CurrentVersion\Explorer\MountPoints2"
                for s in _csubs(_root, MP):
                    kind = ("network share" if s.startswith("##")
                            else "volume GUID" if s.startswith("{") else "drive letter")
                    _ins("MountPoints2",
                         ["user_name", "mount_id", "mount_type", "key_path", "parsed_at"],
                         (_uname, s, kind, MP, cov_stamp),
                         ["user_name", "mount_id"])

                # Map Network Drive MRU - drives this user mapped by hand.
                MND = _pfx + r"Software\Microsoft\Windows\CurrentVersion\Explorer\Map Network Drive MRU"
                for vn, vd, vt in _cvals(_root, MND):
                    if vn == "MRUList":
                        continue
                    _ins("MountPoints2",
                         ["user_name", "mount_id", "mount_type", "key_path", "parsed_at"],
                         (_uname, str(vd), "mapped network drive", MND, cov_stamp),
                         ["user_name", "mount_id"])

                # RDP client - servers this user connected TO (outbound RDP).
                TSC = _pfx + r"Software\Microsoft\Terminal Server Client"
                for vn, vd, vt in _cvals(_root, TSC + r"\Default"):
                    _ins("RDPClientMRU",
                         ["user_name", "entry_type", "server", "username_hint",
                          "key_path", "parsed_at"],
                         (_uname, "MRU", str(vd), "", TSC + r"\Default", cov_stamp),
                         ["user_name", "entry_type", "server"])
                for s in _csubs(_root, TSC + r"\Servers"):
                    hint, _p = _cv(_root, TSC + r"\Servers\\" + s, "UsernameHint")
                    _ins("RDPClientMRU",
                         ["user_name", "entry_type", "server", "username_hint",
                          "key_path", "parsed_at"],
                         (_uname, "Server", s, str(hint or ""), TSC + r"\Servers",
                          cov_stamp),
                         ["user_name", "entry_type", "server"])

                # Office: files opened, and files the user ENABLED CONTENT for.
                OFF = _pfx + r"Software\Microsoft\Office"
                for ver in _csubs(_root, OFF):
                    for prod in _csubs(_root, OFF + "\\" + ver):
                        for leaf, kind in (
                                ("File MRU", "MRU"),
                                (r"Security\Trusted Documents\TrustRecords", "TrustRecord")):
                            kp = "%s\\%s\\%s" % (OFF + "\\" + ver, prod, leaf)
                            for vn, vd, vt in _cvals(_root, kp):
                                doc = vn if kind == "TrustRecord" else str(vd)
                                _ins("OfficeDocuments",
                                     ["user_name", "application", "version", "kind",
                                      "document", "raw", "key_path", "parsed_at"],
                                     (_uname, prod, ver, kind, doc, _fmt(vd)[:400],
                                      kp, cov_stamp),
                                     ["user_name", "application", "kind", "document"])

                # FeatureUsage - Explorer's own per-program counters.
                FU = _pfx + r"Software\Microsoft\Windows\CurrentVersion\Explorer\FeatureUsage"
                for s in _csubs(_root, FU):
                    for vn, vd, vt in _cvals(_root, FU + "\\" + s):
                        try:
                            cnt = int(vd)
                        except (TypeError, ValueError):
                            cnt = 0
                        _ins("FeatureUsage",
                             ["user_name", "usage_type", "program", "count",
                              "key_path", "parsed_at"],
                             (_uname, s, vn, cnt, FU + "\\" + s, cov_stamp),
                             ["user_name", "usage_type", "program"])

                # Compatibility Assistant - a value name here is a program that ran.
                CA = (_pfx + r"Software\Microsoft\Windows NT\CurrentVersion"
                             r"\AppCompatFlags\Compatibility Assistant\Store")
                for vn, vd, vt in _cvals(_root, CA):
                    _ins("CompatibilityAssistant",
                         ["user_name", "program_path", "blob_size", "key_path", "parsed_at"],
                         (_uname, vn, len(vd) if isinstance(vd, bytes) else 0,
                          CA, cov_stamp),
                         ["user_name", "program_path"])

                # RecentApps - absent on some builds; its presence is version-dependent.
                RA = _pfx + r"Software\Microsoft\Windows\CurrentVersion\Search\RecentApps"
                for s in _csubs(_root, RA):
                    d = {a: b for a, b, _t in _cvals(_root, RA + "\\" + s)}
                    la = d.get("LastAccessedTime")
                    try:
                        la = format_forensic_timestamp(filetime_to_datetime(int(la))) if la else ""
                    except Exception:
                        la = str(la or "")
                    _ins("RecentApps",
                         ["user_name", "app_id", "app_path", "launch_count",
                          "last_accessed", "key_path", "parsed_at"],
                         (_uname, str(d.get("AppId", s)), str(d.get("AppPath", "")),
                          int(d.get("LaunchCount", 0) or 0), la, RA, cov_stamp),
                         ["user_name", "app_id"])

                # Application artifacts - remote-access and archive tools leave
                # host names and file paths behind.
                APPS = (
                    ("PuTTY", r"Software\SimonTatham\PuTTY\Sessions", "session"),
                    ("PuTTY", r"Software\SimonTatham\PuTTY\SshHostKeys", "known host"),
                    ("WinSCP", r"Software\Martin Prikryl\WinSCP 2\Sessions", "session"),
                    ("WinRAR", r"Software\WinRAR\ArcHistory", "archive history"),
                    ("WinRAR", r"Software\WinRAR\DialogEditHistory\ExtrPath", "extract path"),
                    ("7-Zip", r"Software\7-Zip\Compression", "compression history"),
                    ("Sysinternals", r"Software\Sysinternals", "EULA accepted"),
                    ("TeamViewer", r"Software\TeamViewer", "config"),
                    ("FileZilla", r"Software\FileZilla Client", "config"),
                    ("VNC", r"Software\RealVNC", "config"),
                )
                for appname, rel, artifact in APPS:
                    kp = _pfx + rel
                    for vn, vd, vt in _cvals(_root, kp):
                        _ins("ApplicationArtifacts",
                             ["user_name", "application", "artifact", "name",
                              "value", "key_path", "parsed_at"],
                             (_uname, appname, artifact, vn, _fmt(vd)[:400], kp, cov_stamp),
                             ["user_name", "application", "artifact", "name"])
                    for s in _csubs(_root, kp):
                        _ins("ApplicationArtifacts",
                             ["user_name", "application", "artifact", "name",
                              "value", "key_path", "parsed_at"],
                             (_uname, appname, artifact, s, "", kp, cov_stamp),
                             ["user_name", "application", "artifact", "name"])

                # FileExts - the association the USER picked, which outranks the
                # machine default. UserChoice is the deliberate choice; the
                # OpenWith lists are what was merely offered, so they are kept
                # apart rather than flattened together.
                FEX = _pfx + r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts"
                for _ext in _csubs(_root, FEX):
                    _uc, _p = _cv(_root, f"{FEX}\\{_ext}\\UserChoice", "ProgId")
                    if _p and _uc:
                        _ins("file_exts",
                             ["user_name", "extension", "choice_type", "progid",
                              "key_path", "parsed_at"],
                             (_uname, _ext, "UserChoice", str(_uc),
                              f"{FEX}\\{_ext}\\UserChoice", cov_stamp),
                             ["user_name", "extension", "choice_type", "progid"])
                    for _vn, _vd, _vt in _cvals(_root, f"{FEX}\\{_ext}\\OpenWithProgids"):
                        _ins("file_exts",
                             ["user_name", "extension", "choice_type", "progid",
                              "key_path", "parsed_at"],
                             (_uname, _ext, "OpenWithProgids", _vn,
                              f"{FEX}\\{_ext}\\OpenWithProgids", cov_stamp),
                             ["user_name", "extension", "choice_type", "progid"])
                    for _vn, _vd, _vt in _cvals(_root, f"{FEX}\\{_ext}\\OpenWithList"):
                        if _vn == "MRUList":
                            continue
                        _ins("file_exts",
                             ["user_name", "extension", "choice_type", "progid",
                              "key_path", "parsed_at"],
                             (_uname, _ext, "OpenWithList", _fmt(_vd),
                              f"{FEX}\\{_ext}\\OpenWithList", cov_stamp),
                             ["user_name", "extension", "choice_type", "progid"])

                # CIDSizeMRU - applications that opened a common file dialog,
                # most recent first. Each value is UTF-16 followed by a binary
                # tail; decode the whole buffer and cut at the first NUL
                # character. Splitting the raw bytes on b"\x00\x00" lands on an
                # odd boundary and eats the final character ("brave.ex").
                CID = (_pfx + r"Software\Microsoft\Windows\CurrentVersion"
                              r"\Explorer\ComDlg32\CIDSizeMRU")
                _cid_vals = {vn: vd for vn, vd, vt in _cvals(_root, CID)}
                _order = _cid_vals.get("MRUListEx", b"")
                if isinstance(_order, bytes):
                    for _pos in range(0, len(_order) // 4):
                        _idx = int.from_bytes(_order[_pos * 4:_pos * 4 + 4], "little")
                        if _idx == 0xFFFFFFFF:
                            break
                        _raw = _cid_vals.get(str(_idx))
                        if not isinstance(_raw, bytes):
                            continue
                        _app = _raw.decode("utf-16-le", "ignore").split("\x00")[0]
                        if not _app:
                            continue
                        _ins("cid_size_mru",
                             ["user_name", "position", "application", "key_path",
                              "parsed_at"],
                             (_uname, _pos, _app, CID, cov_stamp),
                             ["user_name", "application"])

                # ProgramsCache - the Start menu's own program list, held as a
                # shell-item blob. Record presence and size; decoding the blob is
                # the shellbag parser's job, not this one's.
                SP2 = (_pfx + r"Software\Microsoft\Windows\CurrentVersion"
                              r"\Explorer\StartPage2")
                for _vn, _vd, _vt in _cvals(_root, SP2):
                    if not _vn.startswith("ProgramsCache"):
                        continue
                    _ins("programs_cache",
                         ["user_name", "value_name", "blob_size", "key_path",
                          "parsed_at"],
                         (_uname, _vn, len(_vd) if isinstance(_vd, bytes) else 0,
                          SP2, cov_stamp),
                         ["user_name", "value_name"])

                # Regedit LastKey - the key this user last had selected in
                # regedit.exe. Direct evidence of what they went looking at.
                RGE = (_pfx + r"Software\Microsoft\Windows\CurrentVersion"
                              r"\Applets\Regedit")
                for _vn, _vd, _vt in _cvals(_root, RGE):
                    if _vn not in ("LastKey", "View", "FindFlags"):
                        continue
                    _ins("regedit_lastkey",
                         ["user_name", "name", "value", "key_path", "parsed_at"],
                         (_uname, _vn, _fmt(_vd)[:400], RGE, cov_stamp),
                         ["user_name", "name", "value"])
                for _fav in _csubs(_root, RGE + r"\Favorites"):
                    _fv, _ = _cv(_root, RGE + r"\Favorites", _fav)
                    _ins("regedit_lastkey",
                         ["user_name", "name", "value", "key_path", "parsed_at"],
                         (_uname, "Favorite: " + _fav, _fmt(_fv)[:400],
                          RGE + r"\Favorites", cov_stamp),
                         ["user_name", "name", "value"])

                # Printers\Connections - network printers this user attached.
                # The subkey encodes ,,server,printer with commas for backslashes.
                PRC = _pfx + r"Printers\Connections"
                for _c in _csubs(_root, PRC):
                    _parts = [p for p in _c.split(",") if p]
                    _ins("printer_connections",
                         ["user_name", "connection", "server", "printer",
                          "key_path", "parsed_at"],
                         (_uname, _c,
                          _parts[0] if _parts else "",
                          _parts[1] if len(_parts) > 1 else "",
                          PRC, cov_stamp),
                         ["user_name", "connection"])

                # Explorer\Advanced - what the user could see in Explorer.
                # ShowSuperHidden=1 is the interesting one: it is off by default
                # and turning it on means somebody went looking for system files.
                EXA = (_pfx + r"Software\Microsoft\Windows\CurrentVersion"
                              r"\Explorer\Advanced")
                for _n, _dflt, _why in (
                        ("Hidden", "2",
                         "1 shows hidden files, 2 hides them (default)"),
                        ("ShowSuperHidden", "0",
                         "1 reveals protected OS files - off by default"),
                        ("HideFileExt", "1",
                         "0 shows real extensions, 1 hides them (default)"),
                        ("StartMenuInit", "",
                         "Start menu initialisation version")):
                    _v, _p = _cv(_root, EXA, _n)
                    if not _p:
                        continue
                    _ins("explorer_advanced",
                         ["user_name", "setting", "value", "value_decoded", "default_value",
                          "meaning", "key_path", "parsed_at"],
                         (_uname, _n, str(_v), _cov_dec("explorer_advanced", _n, _v), _dflt, _why, EXA, cov_stamp),
                         ["user_name", "setting"])

            # ----------------------------------------------------- posture keys
            # One table per artifact, each carrying its own stock default so a
            # deviation is readable without a second source. These are separate
            # from SecurityPosture because each is a distinct key an examiner
            # queries by name, not another row in a settings bag.
            cursor.execute('''CREATE TABLE IF NOT EXISTS rdp_tcp (
                setting TEXT, value TEXT, value_decoded TEXT, default_value TEXT, meaning TEXT,
                key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS usbstor_start (
                setting TEXT, value TEXT, decoded TEXT, default_value TEXT,
                key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS windows_script_host (
                setting TEXT, value TEXT, value_decoded TEXT, default_value TEXT, meaning TEXT,
                key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS dnscache_parameters (
                name TEXT, value TEXT, value_decoded TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS files_not_to_snapshot (
                entry TEXT, value TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS winevt_channels (
                channel TEXT, source TEXT, enabled TEXT, max_size TEXT,
                retention TEXT, log_file TEXT, reason TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT,
                parsed_at TEXT)''')

            RDPT = r"SYSTEM\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp"
            for _n, _dflt, _why in (
                    ("PortNumber", "3389", "a non-3389 port hides RDP from a port scan"),
                    ("UserAuthentication", "1", "0 disables NLA"),
                    ("SecurityLayer", "2", "0 is RDP security, 2 is TLS"),
                    ("fDisableCdm", "", "0 allows client drive mapping into the session"),
                    ("MinEncryptionLevel", "3", "encryption strength")):
                _v, _p = _cv(HKLM_R, RDPT, _n)
                if not _p:
                    continue
                _ins("rdp_tcp",
                     ["setting", "value", "value_decoded", "default_value", "meaning", "key_path",
                      "parsed_at"],
                     (_n, str(_v), _cov_dec("rdp_tcp", _n, _v), _dflt, _why, RDPT, cov_stamp),
                     ["setting", "key_path"])

            # usbstor Start: 3 is the normal on-demand driver start, 4 is
            # disabled - a deliberate act, and one that stops USB history from
            # being written at all.
            USBS = r"SYSTEM\CurrentControlSet\Services\usbstor"
            _v, _p = _cv(HKLM_R, USBS, "Start")
            if _p:
                _ins("usbstor_start",
                     ["setting", "value", "decoded", "default_value", "key_path",
                      "parsed_at"],
                     ("Start", str(_v),
                      {0: "boot", 1: "system", 2: "automatic", 3: "manual (normal)",
                       4: "DISABLED - USB storage blocked"}.get(_v, "unknown"),
                      "3", USBS, cov_stamp),
                     ["setting", "key_path"])

            # Windows Script Host: the key is usually absent, which means
            # enabled. An explicit Enabled=0 is someone turning scripting off.
            WSH = r"SOFTWARE\Microsoft\Windows Script Host\Settings"
            # Only Enabled/TrustPolicy/Remote were read, and a stock Windows 11
            # sets none of them - so this table was empty on a machine whose key
            # holds four other values, including UseWINSAFER. Absence of the
            # first three is itself the finding ("absent = enabled"), so they
            # stay; the rest are added because they exist and one of them
            # decides whether scripts obey software-restriction policy.
            for _n, _why in (("Enabled", "0 blocks .vbs/.js execution via WSH"),
                             ("TrustPolicy", "signature policy for scripts"),
                             ("Remote", "remote script execution"),
                             ("UseWINSAFER",
                              "0 makes WSH ignore software restriction policy, "
                              "so a blocked script runs anyway"),
                             ("ActiveDebugging", "1 permits script debugging"),
                             ("SilentTerminate",
                              "1 suppresses script error dialogs, hiding failures"),
                             ("DisplayLogo", "cosmetic WSH banner")):
                _v, _p = _cv(HKLM_R, WSH, _n)
                if not _p:
                    continue
                _ins("windows_script_host",
                     ["setting", "value", "value_decoded", "default_value", "meaning", "key_path",
                      "parsed_at"],
                     (_n, str(_v), _cov_dec("windows_script_host", _n, _v), "(absent = enabled)", _why, WSH, cov_stamp),
                     ["setting", "key_path"])

            DNSP = r"SYSTEM\CurrentControlSet\Services\Dnscache\Parameters"
            for _vn, _vd, _vt in _cvals(HKLM_R, DNSP):
                _ins("dnscache_parameters",
                     ["name", "value", "value_decoded", "key_path", "parsed_at"],
                     (_vn, _fmt(_vd)[:400], _cov_dec("dnscache_parameters", _vn, _vd), DNSP, cov_stamp),
                     ["name", "key_path"])

            # FilesNotToSnapshot - files VSS deliberately drops from shadow
            # copies. Normally empty; an entry here is an anti-forensic tell,
            # because it removes the file from the copies an examiner relies on.
            FNTS = r"SYSTEM\CurrentControlSet\Control\BackupRestore\FilesNotToSnapshot"
            for _sub in _csubs(HKLM_R, FNTS):
                for _vn, _vd, _vt in _cvals(HKLM_R, f"{FNTS}\\{_sub}"):
                    _ins("files_not_to_snapshot",
                         ["entry", "value", "key_path", "parsed_at"],
                         (f"{_sub}!{_vn}", _fmt(_vd)[:400],
                          f"{FNTS}\\{_sub}", cov_stamp),
                         ["entry", "key_path"])
            for _vn, _vd, _vt in _cvals(HKLM_R, FNTS):
                _ins("files_not_to_snapshot",
                     ["entry", "value", "key_path", "parsed_at"],
                     (_vn, _fmt(_vd)[:400], FNTS, cov_stamp),
                     ["entry", "key_path"])

            # Event log configuration, from the two places it actually lives.
            #
            # The classic Security/System/Application logs are NOT under
            # WINEVT\Channels - they are legacy EventLog services keys. Only the
            # Vista-era channels live under WINEVT, and there are ~1166 of them,
            # ~788 disabled as shipped. Writing all of them would bury the
            # finding in noise, so record: every legacy log, every channel an
            # examiner asks about by name, and any channel someone has resized.
            EVL = r"SYSTEM\CurrentControlSet\Services\EventLog"
            for _log in _csubs(HKLM_R, EVL):
                _vals = {n: d for n, d, t in _cvals(HKLM_R, f"{EVL}\\{_log}")}
                if not _vals:
                    continue
                _ins("winevt_channels",
                     ["channel", "source", "enabled", "max_size", "retention",
                      "log_file", "reason", "key_path", "parsed_at"],
                     (_log, "EventLog (classic)", "n/a",
                      str(_vals.get("MaxSize", "")), str(_vals.get("Retention", "")),
                      str(_vals.get("File", "")), "classic log",
                      f"{EVL}\\{_log}", cov_stamp),
                     ["channel", "source"])

            WEVT = r"SOFTWARE\Microsoft\Windows\CurrentVersion\WINEVT\Channels"
            _WATCH = (
                "Microsoft-Windows-PowerShell/Operational",
                "Microsoft-Windows-Sysmon/Operational",
                "Microsoft-Windows-TaskScheduler/Operational",
                "Microsoft-Windows-TerminalServices-LocalSessionManager/Operational",
                "Microsoft-Windows-TerminalServices-RemoteConnectionManager/Operational",
                "Microsoft-Windows-Windows Defender/Operational",
                "Microsoft-Windows-WMI-Activity/Operational",
                "Microsoft-Windows-Windows Firewall With Advanced Security/Firewall",
                "Microsoft-Windows-Bits-Client/Operational",
                "Microsoft-Windows-DNS-Client/Operational",
                "Microsoft-Windows-AppLocker/EXE and DLL",
                "Microsoft-Windows-CodeIntegrity/Operational",
                "Windows PowerShell",
            )
            _watch_lower = {w.lower() for w in _WATCH}
            for _ch in _csubs(HKLM_R, WEVT):
                _vals = {n: d for n, d, t in _cvals(HKLM_R, f"{WEVT}\\{_ch}")}
                _watched = _ch.lower() in _watch_lower
                _resized = "MaxSize" in _vals
                if not (_watched or _resized):
                    continue          # default analytic/debug channel - noise
                _ins("winevt_channels",
                     ["channel", "source", "enabled", "max_size", "retention",
                      "log_file", "reason", "key_path", "parsed_at"],
                     (_ch, "WINEVT", str(_vals.get("Enabled", "")),
                      str(_vals.get("MaxSize", "")), str(_vals.get("Retention", "")),
                      "", "watched channel" if _watched else "non-default MaxSize",
                      f"{WEVT}\\{_ch}", cov_stamp),
                     ["channel", "source"])

            # ------------------------------------------------- device attribution
            cursor.execute('''CREATE TABLE IF NOT EXISTS wpdbusenum (
                device_id TEXT, friendly_name TEXT, volume_guid TEXT,
                key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS device_classes (
                class_guid TEXT, class_name TEXT, device_instance TEXT,
                key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS volume_info_cache (
                drive_letter TEXT, volume_label TEXT, file_system TEXT,
                key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''')

            # WPDBUSENUM ties a USB volume GUID to the device that provided it -
            # the missing hop between USBSTOR (which device) and MountedDevices
            # (which drive letter).
            WPD = r"SYSTEM\CurrentControlSet\Enum\SWD\WPDBUSENUM"
            for _dev in _csubs(HKLM_R, WPD):
                _fn, _ = _cv(HKLM_R, f"{WPD}\\{_dev}", "FriendlyName")
                _guid = ""
                if "#" in _dev:
                    _guid = _dev.split("#")[0]
                _ins("wpdbusenum",
                     ["device_id", "friendly_name", "volume_guid", "key_path",
                      "parsed_at"],
                     (_dev, str(_fn or ""), _guid, f"{WPD}\\{_dev}", cov_stamp),
                     ["device_id"])

            # DeviceClasses: first-arrival records per class GUID. Only the disk
            # and volume classes are useful here - the full set is thousands of
            # rows of keyboards and audio endpoints.
            DVC = r"SYSTEM\CurrentControlSet\Control\DeviceClasses"
            for _cls, _label in (
                    ("{53f56307-b6bf-11d0-94f2-00a0c91efb8b}", "Disk"),
                    ("{53f5630d-b6bf-11d0-94f2-00a0c91efb8b}", "Volume"),
                    ("{53f56308-b6bf-11d0-94f2-00a0c91efb8b}", "Storage adapter"),
                    ("{a5dcbf10-6530-11d2-901f-00c04fb951ed}", "USB device")):
                for _inst in _csubs(HKLM_R, f"{DVC}\\{_cls}"):
                    _ins("device_classes",
                         ["class_guid", "class_name", "device_instance",
                          "key_path", "parsed_at"],
                         (_cls, _label, _inst, f"{DVC}\\{_cls}", cov_stamp),
                         ["class_guid", "device_instance"])

            # VolumeInfoCache maps a drive letter to the label the user saw.
            #
            # Two locations, and only the Explorer one was read - which does not
            # exist on Windows 11, so this table was empty while Windows Search
            # held three volumes. The value names differ too: Windows Search
            # writes VolumeLabel/DriveType where Explorer wrote
            # _LabelFromReg/FileSystem, so pointing at the right key alone would
            # still have produced blank rows. Both are tried, both naming
            # schemes are accepted, and whichever exists wins.
            for VIC in (r"SOFTWARE\Microsoft\Windows Search\VolumeInfoCache",
                        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\VolumeInfoCache"):
                for _drv in _csubs(HKLM_R, VIC):
                    _kp = f"{VIC}\\{_drv}"
                    _lbl, _ = _cv(HKLM_R, _kp, "VolumeLabel")
                    if not _lbl:
                        _lbl, _ = _cv(HKLM_R, _kp, "_LabelFromReg")
                    _fs, _ = _cv(HKLM_R, _kp, "FileSystem")
                    if not _fs:
                        # Windows Search stores the numeric DriveType instead of
                        # a file-system name; 3 is a fixed disk, 2 removable.
                        _dt, _ = _cv(HKLM_R, _kp, "DriveType")
                        _fs = {2: "Removable", 3: "Fixed", 4: "Network",
                               5: "CD-ROM", 6: "RAM disk"}.get(_dt, _dt)
                    _ins("volume_info_cache",
                         ["drive_letter", "volume_label", "file_system", "key_path",
                          "parsed_at"],
                         (_drv, str(_lbl or ""), str(_fs or ""), _kp, cov_stamp),
                         ["drive_letter"])

            # ---------------------------------------------------- host identity
            cursor.execute('''CREATE TABLE IF NOT EXISTS machine_guid (
                name TEXT, value TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS product_options (
                name TEXT, value TEXT, meaning TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT,
                parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS os_install_history (
                name TEXT, value TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS active_computer_name (
                name TEXT, value TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS hivelist (
                hive TEXT, file_path TEXT, key_path TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS system_environment (
                name TEXT, value TEXT, value_decoded TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS network_adapters (
                adapter_guid TEXT, name TEXT, value TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT,
                parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS group_policy_history (
                scope TEXT, gpo_id TEXT, name TEXT, value TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT,
                parsed_at TEXT)''')

            # MachineGuid survives reimaging of the user profile and is the
            # steadiest single identifier for "is this the same host".
            CRYP = r"SOFTWARE\Microsoft\Cryptography"
            _v, _p = _cv(HKLM_R, CRYP, "MachineGuid")
            if _p:
                _ins("machine_guid", ["name", "value", "key_path", "parsed_at"],
                     ("MachineGuid", str(_v), CRYP, cov_stamp), ["name"])

            PROD = r"SYSTEM\CurrentControlSet\Control\ProductOptions"
            for _n, _why in (("ProductType",
                              "WinNT is a workstation, ServerNT/LanmanNT a server"),
                             ("ProductSuite", "installed SKU suites")):
                _v, _p = _cv(HKLM_R, PROD, _n)
                if _p:
                    _ins("product_options",
                         ["name", "value", "meaning", "key_path", "parsed_at"],
                         (_n, _fmt(_v), _why, PROD, cov_stamp), ["name"])

            # SYSTEM\Setup keeps the trail of in-place upgrades: which build the
            # machine came from, and when.
            STP = r"SYSTEM\Setup"
            for _vn, _vd, _vt in _cvals(HKLM_R, STP):
                _ins("os_install_history",
                     ["name", "value", "key_path", "parsed_at"],
                     (_vn, _fmt(_vd)[:400], STP, cov_stamp), ["name", "key_path"])
            for _sub in _csubs(HKLM_R, STP):
                if not _sub.lower().startswith("source os"):
                    continue
                for _vn, _vd, _vt in _cvals(HKLM_R, f"{STP}\\{_sub}"):
                    _ins("os_install_history",
                         ["name", "value", "key_path", "parsed_at"],
                         (f"{_sub}!{_vn}", _fmt(_vd)[:400],
                          f"{STP}\\{_sub}", cov_stamp), ["name", "key_path"])

            # ActiveComputerName is the name in use for this boot; it can differ
            # from ComputerName after a rename that has not been rebooted.
            ACN = r"SYSTEM\CurrentControlSet\Control\ComputerName\ActiveComputerName"
            for _vn, _vd, _vt in _cvals(HKLM_R, ACN):
                _ins("active_computer_name",
                     ["name", "value", "key_path", "parsed_at"],
                     (_vn, _fmt(_vd), ACN, cov_stamp), ["name"])

            # hivelist names the backing file of every loaded hive - which is how
            # an examiner confirms the hives they collected are the ones in use.
            HVL = r"SYSTEM\CurrentControlSet\Control\hivelist"
            for _vn, _vd, _vt in _cvals(HKLM_R, HVL):
                _ins("hivelist", ["hive", "file_path", "key_path", "parsed_at"],
                     (_vn, _fmt(_vd), HVL, cov_stamp), ["hive"])

            SENV = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
            for _vn, _vd, _vt in _cvals(HKLM_R, SENV):
                _ins("system_environment",
                     ["name", "value", "value_decoded", "key_path", "parsed_at"],
                     (_vn, _fmt(_vd)[:1000], _cov_dec("system_environment", _vn, _vd), SENV, cov_stamp), ["name"])

            # Adapter GUID -> the name shown in ncpa.cpl, so a Tcpip interface
            # GUID elsewhere in the case can be named.
            NETC = (r"SYSTEM\CurrentControlSet\Control\Network"
                    r"\{4d36e972-e325-11ce-bfc1-08002be10318}")
            for _ad in _csubs(HKLM_R, NETC):
                if _ad.lower() == "descriptions":
                    continue
                for _n in ("Name", "PnpInstanceID"):
                    _v, _p = _cv(HKLM_R, f"{NETC}\\{_ad}\\Connection", _n)
                    if _p:
                        _ins("network_adapters",
                             ["adapter_guid", "name", "value", "key_path",
                              "parsed_at"],
                             (_ad, _n, _fmt(_v),
                              f"{NETC}\\{_ad}\\Connection", cov_stamp),
                             ["adapter_guid", "name"])

            GPH = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Group Policy\History"
            for _scope in _csubs(HKLM_R, GPH):
                for _gpo in _csubs(HKLM_R, f"{GPH}\\{_scope}"):
                    for _vn, _vd, _vt in _cvals(HKLM_R, f"{GPH}\\{_scope}\\{_gpo}"):
                        _ins("group_policy_history",
                             ["scope", "gpo_id", "name", "value", "key_path",
                              "parsed_at"],
                             (_scope, _gpo, _vn, _fmt(_vd)[:400],
                              f"{GPH}\\{_scope}\\{_gpo}", cov_stamp),
                             ["scope", "gpo_id", "name"])

            conn.commit()
            _tot = sum(cov_counts.values())
            print("Forensic coverage collected: %d rows (%s)"
                  % (_tot, ", ".join("%s=%d" % (k, v) for k, v in sorted(cov_counts.items()))))

        except Exception as e:
            logging.error(f"Error collecting forensic coverage keys: {e}")
            print(f"Warning: Could not collect forensic coverage data: {e}")
        # ------------------------------------------------------------------
        # Other users (HKEY_USERS)
        #
        # Everything above reads HKEY_CURRENT_USER, which is only the account
        # running Crow-Eye. On a multi-user machine every other user's activity
        # was being missed silently - no error, just absent rows.
        #
        # HKU\<SID>\... returns byte-identical data to HKCU\... for the current
        # user (verified across UserAssist, RecentDocs, RunMRU, TypedPaths,
        # WordWheelQuery, MuiCache and BagMRU), so this pass can only add users.
        # Shellbags are the exception: they live in UsrClass.dat, mounted as a
        # SEPARATE hive at HKU\<SID>_Classes, not under HKU\<SID>.
        # ------------------------------------------------------------------
        try:
            HKU_R = winreg.HKEY_USERS
            # Re-derived locally rather than inherited from the persistence block:
            # if that block raised, these would not exist and this pass would die
            # with a NameError instead of collecting anything.
            HKLM_R = winreg.HKEY_LOCAL_MACHINE
            RD64 = winreg.KEY_READ | winreg.KEY_WOW64_64KEY
            PROFILE_LIST_PATH = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList"
            _cu_sid = get_current_user_sid()
            current_username = get_username_from_sid(_cu_sid) if _cu_sid else None
            user_stamp = format_forensic_timestamp(get_current_utc())

            def _add_user_column(table):
                """Additive migration - existing case DBs gain the column in place."""
                cursor.execute(f"PRAGMA table_info({table})")
                cols = [c[1] for c in cursor.fetchall()]
                if cols and "user_name" not in cols:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN user_name TEXT")
                    return True
                return False

            PER_USER_TABLES = ["RecentDocs", "RunMRU", "TypedPaths", "MUICache",
                               "OpenSaveMRU", "LastSaveMRU", "Shellbags",
                               "WordWheelQuery"]
            for _t in PER_USER_TABLES:
                _add_user_column(_t)

            # Same additive migration for the MRU key timestamp. An MRU list has
            # no per-entry time, so access_date stays empty and this records the
            # key's own last-write instead - a fact about the key, not a guess
            # about which entry it belongs to.
            for _t in ("RunMRU", "WordWheelQuery", "OpenSaveMRU", "LastSaveMRU"):
                cursor.execute(f"PRAGMA table_info({_t})")
                _cols = [c[1] for c in cursor.fetchall()]
                if _cols and "key_last_write" not in _cols:
                    cursor.execute(
                        f"ALTER TABLE {_t} ADD COLUMN key_last_write TEXT")

            # And the subtractive one. OpenSaveMRU and RecentDocs carried
            # last_written / time_basis, which the time-basis pass fills for any
            # table that has them AND a column it recognises as naming a key.
            # It recognises the name "subkey" - but in these two tables subkey
            # is a file extension (".jpg", "exe"), never a key path, so the
            # match never happened and both columns were empty on every row of
            # every case ever parsed. An empty column is not a neutral thing on
            # screen: these two sat between row_data and parsed_at, so a tab
            # filling positionally showed the parse time under "Last Written".
            #
            # Written one statement at a time on purpose: a (name, DDL) tuple
            # list is what Regclaw uses to BUILD tables, and Sentinel's
            # extract-schema.js reads that shape as a table definition - a loop
            # over pairs here would add phantom tables named after columns.
            for _t in ("OpenSaveMRU", "RecentDocs"):
                cursor.execute(f"PRAGMA table_info({_t})")
                _cols = [c[1] for c in cursor.fetchall()]
                if not _cols:
                    continue
                try:
                    if "last_written" in _cols:
                        cursor.execute(f"ALTER TABLE {_t} DROP COLUMN last_written")
                    if "time_basis" in _cols:
                        cursor.execute(f"ALTER TABLE {_t} DROP COLUMN time_basis")
                except sqlite3.Error as _drop_err:
                    # DROP COLUMN needs SQLite 3.35+. On anything older the
                    # columns simply stay; the tabs place values by name now,
                    # so they render as two empty columns rather than shifting
                    # anything. Worth a line in the log, not a failed parse.
                    logging.debug("dropping dead columns from %s: %s", _t, _drop_err)

            # Migration only. The HKCU passes now stamp user_name at INSERT
            # time, so on a database this build wrote there is nothing left to
            # back-fill. This catches rows written by an older build, which
            # stored NULL and relied on this UPDATE.
            #
            # Attribution must not depend on this step: it runs at the end of
            # the parse, so a guard that includes user_name would stop matching
            # its own rows on the next parse and duplicate the whole table.
            if current_username:
                for _t in PER_USER_TABLES:
                    cursor.execute(
                        f"UPDATE {_t} SET user_name = ? WHERE user_name IS NULL",
                        (current_username,))

            # SID -> profile name, from ProfileList.
            sid_names = {}
            try:
                with winreg.OpenKey(HKLM_R, PROFILE_LIST_PATH, 0, RD64) as _pk:
                    for _i in range(winreg.QueryInfoKey(_pk)[0]):
                        _sid = winreg.EnumKey(_pk, _i)
                        try:
                            with winreg.OpenKey(_pk, _sid, 0, RD64) as _sk:
                                _pp, _ = winreg.QueryValueEx(_sk, "ProfileImagePath")
                                sid_names[_sid] = os.path.basename(_pp)
                        except OSError:
                            pass
            except OSError as e:
                logging.warning(f"ProfileList unreadable: {e}")

            loaded = []
            try:
                with winreg.OpenKey(HKU_R, "", 0, RD64) as _uk:
                    for _i in range(winreg.QueryInfoKey(_uk)[0]):
                        loaded.append(winreg.EnumKey(_uk, _i))
            except OSError as e:
                logging.warning(f"HKEY_USERS unreadable: {e}")

            # Same widening as the coverage walk above: the service hives and
            # .DEFAULT come too, and carry their own labels. The set of service
            # SIDs that used to be excluded here now lives in user_identity,
            # where it names them instead of dropping them.
            other_sids = [s for s in loaded
                          if not s.endswith("_Classes")
                          and s != _cu_sid
                          and (s.startswith("S-1-5-21")
                               or user_identity.is_system_account_key(s))]

            other_rows = 0
            for sid in other_sids:
                # MACHINE\username, the form user_identity.display_owner
                # defines as canonical and the offline parser writes. The
                # ProfileList basename alone produced "HKU\Ghass Active Setup"
                # beside "HKU\CROW-PC\Ghass User Shell Folders" - the same
                # user under two labels, in one table, from one parser.
                # A service hive is named, never resolved: LookupAccountSid
                # would return "NT AUTHORITY\SYSTEM", which reads like an
                # account a person could log in as.
                uname = (user_identity.system_account_label(sid)
                         or get_username_from_sid(sid)
                         or sid_names.get(sid) or sid)
                base = sid + "\\Software\\Microsoft\\Windows\\CurrentVersion"

                # Run / RunOnce -> AutoStartPrograms, keyed by user so two users
                # with the same entry name cannot collide on the primary key.
                for rk in ("Run", "RunOnce"):
                    for nm, (dt, _ty) in reg_Claw_live(HKU_R, f"{base}\\{rk}").items():
                        loc = f"HKU\\{uname} {rk}"
                        if not check_exists(cursor, 'AutoStartPrograms',
                                            ['location', 'program_name'], (loc, nm)):
                            cursor.execute(
                                'INSERT INTO AutoStartPrograms '
                                '(location, program_name, command, record_state, parsed_at) '
                                'VALUES (?, ?, ?, ?, ?)', (loc, nm, str(dt), LIVE_STATE, user_stamp))
                            other_rows += 1

                # TypedPaths - Explorer address bar entries.
                #
                # Guarded, like every insert here: none of these tables carries a
                # UNIQUE or PRIMARY KEY, so an unguarded INSERT appends the whole
                # set again on every re-parse - once per extra loaded profile. It
                # raises nothing; the row count just grows, which reads as more
                # evidence rather than a bug.
                _tp_path = f"{base}\\Explorer\\TypedPaths"
                _u_tp_lastwrite = key_last_write_live(HKU_R, _tp_path)
                for nm, (dt, ty) in reg_Claw_live(HKU_R, _tp_path).items():
                    _pos = -1
                    if nm[:3].lower() == 'url' and nm[3:].isdigit():
                        _pos = int(nm[3:]) - 1
                    if check_exists(cursor, 'TypedPaths',
                                    ['name', 'row_data', 'user_name'],
                                    (nm, str(dt), uname)):
                        continue
                    cursor.execute(
                        'INSERT INTO TypedPaths (name, row_data, type, user_name, '
                        'mru_position, key_last_write, parsed_at) '
                        'VALUES (?, ?, ?, ?, ?, ?, ?)',
                        (nm, str(dt), ty, uname, _pos, _u_tp_lastwrite, user_stamp))
                    other_rows += 1

                # RunMRU - commands typed into the Run dialog.
                _rm_path = f"{base}\\Explorer\\RunMRU"
                _rm = reg_Claw_live(HKU_R, _rm_path)
                _rm_kw = key_last_write_live(HKU_R, _rm_path)
                _mru = str(_rm.get("MRUList", ("", ""))[0])
                for nm, (dt, _ty) in _rm.items():
                    if nm == "MRUList":
                        continue
                    try:
                        p = registry_binary_parser.parse_runmru_entry(nm, str(dt), _mru)
                        # user_name is part of the key: two accounts can type the
                        # same command, and both are evidence.
                        if check_exists(cursor, 'RunMRU', ['command', 'user_name'],
                                        (p.get('command'), uname)):
                            continue
                        cursor.execute(
                            'INSERT INTO RunMRU (command, mru_position, access_date, '
                            'key_last_write, parsed_at, user_name) '
                            'VALUES (?, ?, ?, ?, ?, ?)',
                            (p.get('command'), p.get('mru_position'),
                             p.get('access_date'), _rm_kw, user_stamp, uname))
                        other_rows += 1
                    except Exception as e:
                        logging.debug(f"RunMRU {uname}/{nm}: {e}")

                # MUICache - application display names, an execution signal.
                # Pivoted to one row per executable, as in the current-user pass.
                _u_apps = {}
                for mui in (r"\Software\Classes\Local Settings\Software\Microsoft\Windows\Shell\MuiCache",
                            r"\Software\Microsoft\Windows\ShellNoRoam\MUICache"):
                    for nm, (dt, _ty) in reg_Claw_live(HKU_R, sid + mui).items():
                        try:
                            p = registry_binary_parser.parse_muicache_entry(nm, str(dt))
                            if not p or not p.get('app_path'):
                                continue
                            _pr = (p.get('muicache_property') or '').lower()
                            _e = _u_apps.setdefault(
                                p['app_path'],
                                {'file_extension': p.get('file_extension', ''),
                                 'app_name': '', 'company': ''})
                            if _pr == 'applicationcompany':
                                _e['company'] = str(dt).strip()
                            elif _pr in ('friendlyappname', 'applicationname'):
                                _e['app_name'] = str(dt).strip()
                            elif not _e['app_name'] and not _pr:
                                _e['app_name'] = str(dt).strip()
                        except Exception as e:
                            logging.debug(f"MUICache {uname}/{nm}: {e}")
                for _ap, _e in _u_apps.items():
                    # Keyed by user as well as path - the same program run by
                    # two accounts is two findings, not one.
                    if check_exists(cursor, 'MUICache',
                                    ['app_path', 'user_name'], (_ap, uname)):
                        continue
                    cursor.execute(
                        'INSERT INTO MUICache (app_path, app_name, company, '
                        'file_extension, parsed_at, user_name) '
                        'VALUES (?, ?, ?, ?, ?, ?)',
                        (_ap, _e['app_name'], _e['company'],
                         _e['file_extension'], user_stamp, uname))
                    other_rows += 1

                # UserAssist - GUID subkeys, ROT13 names, binary counters.
                ua_base = sid + r"\Software\Microsoft\Windows\CurrentVersion\Explorer\UserAssist"
                for guid in get_subkeys_live(HKU_R, ua_base) or {}:
                    for nm, (dt, _ty) in reg_Claw_live(
                            HKU_R, f"{ua_base}\\{guid}\\Count").items():
                        try:
                            if not isinstance(dt, bytes):
                                continue
                            p = registry_binary_parser.parse_userassist_entry(nm, dt)
                            if not p or not p.get('program_path'):
                                continue
                            # Guarded, and tolerant of the enriched SID form.
                            if user_identity.row_exists_for_sid(
                                    cursor, 'UserAssist', ['program_path'],
                                    (p.get('program_path'),), 'user_sid', sid):
                                continue
                            cursor.execute(
                                'INSERT INTO UserAssist (program_path, run_count, '
                                'last_execution, focus_count, focus_time, user_sid, '
                                'parsed_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                                (p.get('program_path'), p.get('run_count'),
                                 p.get('last_execution'), p.get('focus_count'),
                                 p.get('focus_time'), sid, user_stamp))
                            other_rows += 1
                        except Exception as e:
                            logging.debug(f"UserAssist {uname}: {e}")

                # Shellbags - UsrClass.dat is a separate hive: HKU\<SID>_Classes.
                #
                # Through the same store function the current-user pass uses, so
                # every account gets the same 16 decoded fields. This block used
                # to call .get() on the walker's tuples, which raises on every
                # entry - so it silently wrote nothing at all for other users.
                try:
                    sb = enumerate_shellbags_recursive(
                        HKU_R,
                        sid + r"_Classes\Local Settings\Software\Microsoft\Windows\Shell\BagMRU")
                    other_rows += store_shellbag_entries(sb or [], uname)
                except Exception as e:
                    logging.debug(f"Shellbags {uname}: {e}")

                # RecentDocs - documents opened by this account.
                # 'main' matches the current-user pass and the offline parser.
                rd_base = base + r"\Explorer\RecentDocs"
                _rd_keys = {"main": reg_Claw_live(HKU_R, rd_base)}
                _rd_keys.update(get_subkeys_live(HKU_R, rd_base) or {})
                for _sub, _vals in _rd_keys.items():
                    _u_order = mru_order_live(_vals)
                    _u_lw = key_last_write_live(
                        HKU_R, rd_base if _sub == "main" else f"{rd_base}\\{_sub}")
                    for nm, (dt, ty) in (_vals or {}).items():
                        if nm.lower() == 'mrulistex':
                            continue
                        try:
                            if ty == 'REG_BINARY' and isinstance(dt, bytes):
                                fn = registry_binary_parser.parse_recentdocs_entry(dt) or str(dt)
                            else:
                                fn = str(dt)
                            _pos = -1
                            try:
                                _i = int(nm)
                                if _u_order and _i in _u_order:
                                    _pos = _u_order.index(_i)
                            except (ValueError, TypeError):
                                pass
                            if check_exists(cursor, 'RecentDocs',
                                            ['subkey', 'name', 'row_data', 'user_name'],
                                            (_sub, nm, fn, uname)):
                                continue
                            cursor.execute(
                                'INSERT INTO RecentDocs (subkey, name, row_data, '
                                'type, user_name, mru_position, key_last_write, '
                                'parsed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                                (_sub, nm, fn, ty, uname, _pos, _u_lw, user_stamp))
                            other_rows += 1
                        except Exception as e:
                            logging.debug(f"RecentDocs {uname}/{nm}: {e}")

                # WordWheelQuery - Explorer search box history.
                _ww_path = f"{base}\\Explorer\\WordWheelQuery"
                _ww_kw = key_last_write_live(HKU_R, _ww_path)
                for nm, (dt, _ty) in reg_Claw_live(HKU_R, _ww_path).items():
                    if nm.lower() == "mrulistex":
                        continue
                    try:
                        term = (dt.decode("utf-16-le", "ignore").rstrip("\x00")
                                if isinstance(dt, bytes) else str(dt))
                        if not term or check_exists(
                                cursor, 'WordWheelQuery',
                                ['search_term', 'user_name'], (term, uname)):
                            continue
                        cursor.execute(
                            'INSERT INTO WordWheelQuery (search_term, search_type, '
                            'mru_position, key_last_write, parsed_at, user_name) '
                            'VALUES (?, ?, ?, ?, ?, ?)',
                            (term, 'Explorer search', nm, _ww_kw, user_stamp, uname))
                        other_rows += 1
                    except Exception as e:
                        logging.debug(f"WordWheelQuery {uname}/{nm}: {e}")

                # OpenSaveMRU / LastSaveMRU - shell Open/Save dialog history.
                _cdlg = base + r"\Explorer\ComDlg32"
                for _ext, _vals in (get_subkeys_live(
                        HKU_R, _cdlg + r"\OpenSavePidlMRU") or {}).items():
                    for nm, (dt, _ty) in (_vals or {}).items():
                        if nm.lower() == "mrulistex" or not isinstance(dt, bytes):
                            continue
                        try:
                            # Same decoder the current-user pass uses, so a file
                            # resolves identically whichever account opened it.
                            p = registry_binary_parser.parse_opensavemru_entry(dt) or {}
                            fname = p.get('file_name', '')
                            if not fname or check_exists(
                                    cursor, 'OpenSaveMRU',
                                    ['subkey', 'name', 'file_name', 'user_name'],
                                    (_ext, nm, fname, uname)):
                                continue
                            cursor.execute(
                                'INSERT INTO OpenSaveMRU (subkey, name, type, '
                                'file_path, file_name, extension, drive_letter, '
                                'row_data, parsed_at, user_name) '
                                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                                (_ext, nm, 'REG_BINARY', p.get('file_path', ''),
                                 fname, _ext, p.get('drive_letter', ''),
                                 str(dt), user_stamp, uname))
                            other_rows += 1
                        except Exception as e:
                            logging.debug(f"OpenSaveMRU {uname}/{nm}: {e}")

                for nm, (dt, _ty) in reg_Claw_live(
                        HKU_R, _cdlg + r"\LastVisitedPidlMRU").items():
                    if nm.lower() == "mrulistex" or not isinstance(dt, bytes):
                        continue
                    try:
                        p = registry_binary_parser.parse_lastsavemru_entry(dt) or {}
                        app = p.get('application', '')
                        if not app or check_exists(
                                cursor, 'LastSaveMRU',
                                ['mru_number', 'application', 'user_name'],
                                (nm, app, uname)):
                            continue
                        cursor.execute(
                            'INSERT INTO LastSaveMRU (mru_number, type, application, '
                            'folder_path, drive_letter, row_data, parsed_at, '
                            'user_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                            (nm, 'REG_BINARY', app, p.get('folder_path', ''),
                             p.get('drive_letter', ''), str(dt), user_stamp, uname))
                        other_rows += 1
                    except Exception as e:
                        logging.debug(f"LastSaveMRU {uname}/{nm}: {e}")

            # Per-user autostart locations, for every loaded user hive.
            #
            # Kept out of the other_sids loop above on purpose: that loop skips
            # the account running Crow-Eye because HKCU is parsed elsewhere, but
            # the persistence block only ever walked HKLM - so on a single-user
            # machine ("Other users: none loaded") these keys were collected for
            # nobody at all, and every one of these tables showed an empty user.
            asep_user_rows = 0
            _asep_sids = list(other_sids)
            if _cu_sid and _cu_sid not in _asep_sids:
                _asep_sids.append(_cu_sid)
            for sid in _asep_sids:
                # MACHINE\username, the form user_identity.display_owner
                # defines as canonical and the offline parser writes. The
                # ProfileList basename alone produced "HKU\Ghass Active Setup"
                # beside "HKU\CROW-PC\Ghass User Shell Folders" - the same
                # user under two labels, in one table, from one parser.
                # A service hive is named, never resolved: LookupAccountSid
                # would return "NT AUTHORITY\SYSTEM", which reads like an
                # account a person could log in as.
                uname = (user_identity.system_account_label(sid)
                         or get_username_from_sid(sid)
                         or sid_names.get(sid) or sid)
            # Per-user autostart locations.
            #
            # The persistence block walks HKLM only, so these tables held
            # machine-wide rows and their user_name column was empty on every
            # row - not because attribution failed, but because no per-user
            # row was ever collected. The HKCU copy of User Shell Folders is
            # the Startup-folder redirect, one of the oldest persistence
            # tricks there is, and it was invisible.
            #
            # Type names and subkey listing are re-derived here rather than
            # inherited from the persistence block: if that block raised,
            # its nested helpers do not exist and this pass would die with a
            # NameError instead of collecting anything.
            def _u_type(t):
                # reg_Claw_live already converts the type to its name, so this
                # receives 'REG_SZ', not winreg.REG_SZ. Looking a string up in
                # an int-keyed map missed every time and the fallback wrote
                # "REG_TYPE_REG_SZ" into the type column.
                if isinstance(t, str):
                    return t
                return {winreg.REG_SZ: "REG_SZ",
                        winreg.REG_EXPAND_SZ: "REG_EXPAND_SZ",
                        winreg.REG_MULTI_SZ: "REG_MULTI_SZ",
                        winreg.REG_DWORD: "REG_DWORD",
                        winreg.REG_QWORD: "REG_QWORD",
                        winreg.REG_BINARY: "REG_BINARY",
                        winreg.REG_NONE: "REG_NONE"}.get(t, "REG_TYPE_%s" % t)

            def _user_asep(table, key_suffix, names=None, roll=None):
                """Write one per-user autostart row set, guarded like _record.

                Guarded on (hive, key_path, name); key_path carries the SID,
                so a per-user row can never collide with the machine-wide one
                and a re-parse cannot append the set twice.
                """
                written = 0
                _kp = sid + "\\" + key_suffix
                for _nm, (_dt, _ty) in reg_Claw_live(HKU_R, _kp).items():
                    if names and _nm not in names:
                        continue
                    _val = "; ".join(str(x) for x in _dt) if isinstance(_dt, list) else str(_dt)
                    if not check_exists(cursor, table,
                                        ['hive', 'key_path', 'name'],
                                        ("HKCU", _kp, _nm)):
                        # The per-user hives get the same decoding as the
                        # machine-wide pass - this is a SECOND writer for
                        # the same 27 tables, and updating only _record
                        # left every per-user row undecoded while the
                        # machine-wide ones beside them were fine.
                        # %USERPROFILE% resolves against THIS user's
                        # profile, which is the whole point of doing it
                        # per row rather than once.
                        _u_env = _evidence_env
                        _u_prof = _profile_paths.get(str(uname or '').lower())
                        if _u_prof:
                            _u_env = dict(_evidence_env, USERPROFILE=_u_prof)
                        _u_dec = registry_binary_parser.render_registry_value(
                            table, _nm, _dt, _ty, _u_env)
                        if _u_dec == _val:
                            _u_dec = ''        # a copy is not a decode
                        cursor.execute(
                            'INSERT INTO ' + table + ' (hive, key_path, name, '
                            'data, data_decoded, type, user_name, parsed_at) '
                            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                            ("HKCU", _kp, _nm, _val, _u_dec, _u_type(_ty),
                             uname, user_stamp))
                        written += 1
                    if roll and _val:
                        _loc = "HKU\\" + uname + " " + roll
                        if not check_exists(cursor, 'AutoStartPrograms',
                                            ['location', 'program_name'],
                                            (_loc, _nm)):
                            cursor.execute(
                                'INSERT INTO AutoStartPrograms '
                                '(location, program_name, command, record_state, parsed_at) '
                                'VALUES (?, ?, ?, ?, ?)',
                                (_loc, _nm, _val, LIVE_STATE, user_stamp))
                return written

            try:
                _USF = (r"Software\Microsoft\Windows\CurrentVersion"
                        r"\Explorer\User Shell Folders")
                asep_user_rows += _user_asep("user_shell_folders", _USF,
                                         roll="User Shell Folders")

                # Active Setup StubPath runs once per user at first logon;
                # the per-user half records what already ran for this account.
                _AS = r"Software\Microsoft\Active Setup\Installed Components"
                for _comp in (get_subkeys_live(HKU_R, sid + "\\" + _AS) or []):
                    asep_user_rows += _user_asep(
                        "active_setup", _AS + "\\" + _comp,
                        names={"StubPath", "Version", "IsInstalled"},
                        roll="Active Setup")

                # Valid per-user launch points that are simply absent on a
                # clean machine - which is why one appearing is worth seeing.
                asep_user_rows += _user_asep(
                    "policies_explorer_run",
                    r"Software\Microsoft\Windows\CurrentVersion"
                    r"\Policies\Explorer\Run",
                    roll="Policies Explorer Run")
                asep_user_rows += _user_asep(
                    "command_processor", r"Software\Microsoft\Command Processor",
                    names={"AutoRun"}, roll="Command Processor")
            except Exception as _e:
                logging.debug("per-user ASEP pass failed for %s: %s", sid, _e)

            conn.commit()
            if other_sids:
                print(f"Other users collected: {len(other_sids)} "
                      f"({', '.join(sid_names.get(s, s) for s in other_sids)}), "
                      f"{other_rows} rows")
            else:
                print(f"Other users: none loaded besides {current_username or 'current user'}")
            print(f"Per-user autostart rows: {asep_user_rows} "
                  f"across {len(_asep_sids)} user hive(s)")

        except Exception as e:
            logging.error(f"Error collecting other users: {e}")
            print(f"Warning: Could not collect other-user registry data: {e}")

        # ------------------------------------------------------------------
        # User identity
        #
        # Same call, same module as the offline parser, so a machine yields the
        # same account list and the same names either way.
        #
        # SAM is read from the COLLECTED hive copy, not from HKLM\SAM - that key
        # is unreadable through winreg even elevated (WinError 5). When no copy
        # is present the accounts still build from ProfileList, and the `source`
        # column records what was available.
        # ------------------------------------------------------------------
        try:
            # Use hives the COLLECTOR left in the case, if collection has run.
            # Reading collected evidence is fine; this parser must never write
            # any into the case - Registry_Hives is the collector's output.
            _hive_dir = user_identity.find_hive_dir(db_filename)
            _hives = user_identity.locate_hives(_hive_dir) if _hive_dir else {}

            # SAM is the one hive winreg cannot read at all, so without it the
            # live parser only sees ProfileList and misses account flags, logon
            # counts, and every account that has never logged on - including the
            # built-in Administrator, which has no profile. When collection has
            # not run, export it to a TEMPORARY file that exists only for this
            # block. Needs elevation; degrades quietly without it.
            # SECURITY is the second hive winreg cannot reach - its ROOT key
            # denies Administrators outright, so unlike SAM there is not even a
            # handle to work from. Same export path, same temporary lifetime.
            with user_identity.live_sam_hive() as _tmp_sam, \
                 user_identity.live_security_hive() as _tmp_sec:
                _sam = _hives.get('sam') or _tmp_sam
                _sec = _hives.get('security') or _tmp_sec

                _accts, _enriched = user_identity.apply_identity(
                    cursor,
                    _sam, _hives.get('software'), _hives.get('system'),
                    default_user=current_username,
                    # Live only: read ProfileList and the computer name from THIS
                    # machine when no collected hive copy is available. Never set
                    # on the offline path, which always has hives.
                    allow_live_fallback=True)
                conn.commit()

                # LSA policy, audit policy and secret metadata. Same function
                # the offline parser calls, so both produce the same tables.
                try:
                    _sec_counts = security_hive.parse_security(
                        cursor, _sec, check_exists,
                        format_forensic_timestamp(get_current_utc()))
                    conn.commit()
                    if any(_sec_counts.values()):
                        print("SECURITY hive: "
                              + ", ".join("%s=%d" % (k, v)
                                          for k, v in sorted(_sec_counts.items())))
                    elif _sec:
                        print("SECURITY hive read but no LSA rows written")
                    else:
                        print("SECURITY hive unavailable - LSA tables skipped "
                              "(needs elevation)")
                except Exception as _e:
                    logging.error(f"Error parsing SECURITY hive: {_e}")
                    print(f"Warning: Could not parse SECURITY hive: {_e}")

            if _sam:
                _origin = "collected hives" if _hives.get('sam') else "live SAM"
                print(f"User accounts: {_accts} from {_origin} + ProfileList, "
                      f"{_enriched} SID references resolved to names")
            elif not check_admin_privileges():
                # is_admin is a local of parse_live_registry, not of this
                # function - re-check rather than reach for a name that is not
                # in scope here.
                print(f"User accounts: {_accts} from ProfileList "
                      f"(SAM needs Administrator - re-run elevated for account "
                      f"flags and logon counts), {_enriched} SID references resolved")
            else:
                print(f"User accounts: {_accts} from ProfileList "
                      f"(SAM could not be read - see the log), "
                      f"{_enriched} SID references resolved")

        except Exception as e:
            logging.error(f"Error building user identity: {e}")
            print(f"Warning: Could not build user identity: {e}")

        # ---- what a tree walk, and winreg, cannot reach -----------------
        # Sections 13 and 14 of the registry guide: the class-name field, the
        # shared security descriptors, and the records still sitting in freed
        # cells. None of the three can be read through the registry API - the
        # first two because winreg does not expose them, the third because free
        # cells exist in a FILE and the API has no concept of one.
        #
        # So acquire the hive as a file, the same way SAM and SECURITY have
        # always been read, and run the same walk the offline parser runs.
        # Measured on the machine this was written against: winreg reaches 110
        # keys under Enum\USB and is denied 21 subkeys; the acquired hive
        # reaches 868 and every Properties key with it.
        _hive_routes = {}
        try:
            _walk_stamp = format_forensic_timestamp(get_current_utc())
            _tot = {"c": 0, "s": 0, "k": 0, "v": 0}
            _allow_snapshot = _parser_allows_snapshot_creation()

            # The machine hives, then one pair per user profile. NTUSER.DAT
            # and UsrClass.dat hold Shellbags, RecentDocs, UserAssist, MuiCache
            # and TypedPaths - the per-user activity most investigations turn
            # on - and a parse that walks only the machine hives sees none of
            # it as a file.
            _targets = [(_l, None) for _l in
                        ("SYSTEM", "SOFTWARE", "SAM", "SECURITY", "DEFAULT")]
            try:
                _targets.extend(live_hive_access.user_hives())
            except Exception as _e:
                logging.debug("could not enumerate per-user hives: %s", _e)

            def _fmt_ft(raw):
                """A raw FILETIME as our forensic timestamp, or ""."""
                if not raw:
                    return ""
                try:
                    return format_forensic_timestamp(filetime_to_datetime(raw))
                except Exception:
                    return ""

            _KEY_ROOTS = re.compile(
                r"^(root|cmi-createhive\{[^}]*\}|system|software|sam|security|"
                r"default|ntuser\.dat|usrclass\.dat|hklm|hkcu|hku|"
                r"hkey_local_machine|hkey_current_user|hkey_users)$")

            def _norm_key(path):
                """One spelling for a key, so the two sides of a join meet.

                The walk reports a hive-rooted path and the artifact tables
                store what the parser read, which is not the same string.
                """
                parts = [x for x in (path or "").replace("/", chr(92)).split(chr(92)) if x]
                while parts and _KEY_ROOTS.match(parts[0].lower()):
                    parts.pop(0)
                return chr(92).join(parts).lower()

            def _key_columns(cur):
                """(table, key column) for every table that names its rows' key.

                Derived from the live schema rather than a hardcoded list, so a
                table added later is covered without anyone editing this.
                """
                out = []
                cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
                for (_name,) in cur.fetchall():
                    cur.execute("PRAGMA table_info([%s])" % _name)
                    cols = [r[1] for r in cur.fetchall()]
                    if "last_written" not in cols or "time_basis" not in cols:
                        continue
                    kc = next((c for c in ("key_path", "registry_path", "subkey",
                                           "reg_path") if c in cols), None)
                    if kc:
                        out.append((_name, kc))
                return out

            _pending_changes = []
            _pending_keytimes = []
            for _label, _on_disk in _targets:
                with live_hive_access.acquire_hive(
                        _label, on_disk_path=_on_disk,
                        allow_snapshot_creation=_allow_snapshot) as (_path, _route):
                    _hive_routes[_label] = _route
                    if not _path:
                        continue

                    # The change and key-time reads happen HERE, inside the
                    # acquisition, because the acquired copy is removed when
                    # this block exits. Recording the path for a later pass
                    # points it at a file that no longer exists - which is
                    # exactly what the first version did, reporting 0 changes
                    # across 0 hives while the walk below read these same
                    # files successfully.
                    # The logs have to be fetched explicitly here. Only the
                    # memoised acquired_hive() pulls them; the context-manager
                    # form does not, so without this the acquired copy has no
                    # .LOG1 beside it, find_logs_for() returns nothing and the
                    # change pass reports 0 across 0 hives - which it did,
                    # while the walk in the same loop read the same files fine.
                    try:
                        _src = _on_disk or live_hive_access.STANDARD_HIVES.get(
                            live_hive_access._kind(_label), "")
                        if _src:
                            live_hive_access.acquire_logs(
                                _src, _path,
                                allow_snapshot_creation=_allow_snapshot)
                    except Exception as _exc:
                        logging.debug("logs for %s: %s", _label, _exc)

                    try:
                        for _r in registry_hive_walk.value_changes(_path):
                            _pending_changes.append((_label, _r))
                        for _kt in registry_hive_walk.key_times(_path):
                            if _kt["key_path"] and _kt["timestamp_raw"]:
                                _pending_keytimes.append((_label, _kt))
                    except Exception as _exc:
                        logging.debug("value changes %s: %s", _label, _exc)

                    _w = registry_hive_walk.walk_hive(_path)
                    if _w.error:
                        logging.debug("hive walk %s: %s", _label, _w.error)

                    for _cn in _w.class_names:
                        cursor.execute(
                            'INSERT OR IGNORE INTO registry_class_names '
                            '(hive_name, key_path, key_name, class_name, '
                            'class_length, key_last_write, parsed_at) '
                            'VALUES (?, ?, ?, ?, ?, ?, ?)',
                            (_label, _cn["key_path"], _cn["key_name"],
                             _cn["class_name"], _cn["class_length"],
                             format_forensic_timestamp(_cn["timestamp"])
                             if _cn["timestamp"] else "", _walk_stamp))
                        _tot["c"] += cursor.rowcount if cursor.rowcount > 0 else 0

                    for _sd in _w.security:
                        _d = registry_binary_parser.parse_security_descriptor(
                            _sd["descriptor"])
                        cursor.execute(
                            'INSERT OR IGNORE INTO registry_security_descriptors '
                            '(hive_name, sk_offset, descriptor_hash, '
                            'reference_count, owner_sid, group_sid, '
                            'dacl_ace_count, sacl_ace_count, descriptor_size, '
                            'sample_key_path, parsed_at) '
                            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                            (_label, _sd["sk_offset"],
                             hashlib.sha256(_sd["descriptor"]).hexdigest(),
                             _sd["reference_count"], _d.get("owner_sid", ""),
                             _d.get("group_sid", ""), _d.get("dacl_ace_count"),
                             _d.get("sacl_ace_count"), _d.get("size", 0),
                             _sd["sample_key_path"], _walk_stamp))
                        _tot["s"] += cursor.rowcount if cursor.rowcount > 0 else 0

                    # Only the real file carries freed cells. An NtSaveKeyEx
                    # export is a fresh write of the live tree, so carving it
                    # finds nothing - and writing that down as "no deleted
                    # keys" would be a confident wrong answer about a hive that
                    # may hold thousands.
                    if not live_hive_access.route_can_carve(_route):
                        continue

                    for _ck in _w.carved_keys:
                        _when = ""
                        if _ck["timestamp_raw"]:
                            try:
                                _when = format_forensic_timestamp(
                                    filetime_to_datetime(_ck["timestamp_raw"]))
                            except Exception:
                                _when = ""
                        cursor.execute(
                            'INSERT OR IGNORE INTO registry_carved_keys '
                            '(hive_name, cell_offset, key_name, key_path, '
                            'parent_resolved, key_last_write, subkey_count, '
                            'value_count, record_state, parsed_at) '
                            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                            (_label, _ck["cell_offset"], _ck["key_name"],
                             _ck.get("key_path", ""),
                             1 if _ck.get("parent_resolved") else 0, _when,
                             _ck["subkey_count"], _ck["value_count"],
                             DELETED_STATE, _walk_stamp))
                        _tot["k"] += cursor.rowcount if cursor.rowcount > 0 else 0

                        # The values this key held, with the key that held them.
                        for _kv in _ck.get("values", []):
                            cursor.execute(
                                'INSERT OR IGNORE INTO registry_carved_values '
                                '(hive_name, cell_offset, parent_cell_offset, '
                                'key_path, value_name, value_type, data_size, '
                                'is_inline, data, record_state, parsed_at) '
                                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                                (_label, _kv["cell_offset"], _ck["cell_offset"],
                                 _ck.get("key_path", ""), _kv["value_name"],
                                 _REG_TYPE_NAMES.get(_kv["value_type"], "UNKNOWN"),
                                 _kv["data_size"], 1 if _kv["inline"] else 0,
                                 _carved_data_text(_kv.get("data"), _kv["value_type"]),
                                 DELETED_STATE, _walk_stamp))
                            _tot["v"] += cursor.rowcount if cursor.rowcount > 0 else 0

                    for _cv in _w.carved_values:
                        # Reached without its key, so it carries no path.
                        cursor.execute(
                            'INSERT OR IGNORE INTO registry_carved_values '
                            '(hive_name, cell_offset, parent_cell_offset, '
                            'key_path, value_name, value_type, data_size, '
                            'is_inline, data, record_state, parsed_at) '
                            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                            (_label, _cv["cell_offset"], None, "",
                             _cv["value_name"],
                             _REG_TYPE_NAMES.get(_cv["value_type"], "UNKNOWN"),
                             _cv["data_size"], 1 if _cv["inline"] else 0,
                             _carved_data_text(_cv.get("data"), _cv["value_type"]),
                             DELETED_STATE, _walk_stamp))
                        _tot["v"] += cursor.rowcount if cursor.rowcount > 0 else 0

            # ---- the keys nothing used to read --------------------
            # Nineteen keys that hold real data and were opened by nothing.
            # One corrects a finding rather than adding one: StartupApproved
            # says whether each autostart entry is allowed to launch, and
            # without it every Run value reads as live persistence.
            try:
                K = registry_extra_keys.KEYS
                _HK = {"SYSTEM": winreg.HKEY_LOCAL_MACHINE,
                       "SOFTWARE": winreg.HKEY_LOCAL_MACHINE,
                       "NTUSER": winreg.HKEY_CURRENT_USER}

                def _split(tagged):
                    tag, body = tagged.split("|", 1)
                    root = _HK[tag]
                    if tag == "SYSTEM":
                        body = "SYSTEM" + chr(92) + "CurrentControlSet" + chr(92) + body
                    elif tag == "SOFTWARE":
                        body = "SOFTWARE" + chr(92) + body
                    return root, body

                def _vals(tagged):
                    try:
                        root, body = _split(tagged)
                        return _read_values_at(root, body) or {}
                    except Exception:
                        return {}

                def _subs(tagged):
                    try:
                        root, body = _split(tagged)
                        return _read_subkeys_at(root, body) or []
                    except Exception:
                        return []

                def _sys(rel):
                    return "SYSTEM|" + rel

                def _sw(rel):
                    return "SOFTWARE|" + rel

                def _nt(rel):
                    return "NTUSER|" + rel

                _resolved = {
                    "power": _sys(K["power"]),
                    "nls_language": _sys(K["nls_language"]),
                    "winnt_current_version": _sw(K["winnt_current_version"]),
                    "w32time": _sys(K["w32time"]), "tcpip": _sys(K["tcpip"]),
                    "search_gather": _sw(K["search_gather"]),
                    "shell_folders": _nt(K["shell_folders"]),
                    "taskband": _nt(K["taskband"]),
                    "zone_policy": _nt(K["zone_map"]),
                    "attachments": _nt(K["attachments"]),
                    "device_guard": _sys(K["device_guard"]),
                    "lanman_workstation": _sys(K["lanman_workstation"]),
                }

                _extra = {"n": 0}

                def _put(table, columns, rows):
                    if not rows:
                        return
                    # One choke point for the hive tag, so no collector has to
                    # remember: the tag is how a path is routed to a reader,
                    # never what gets stored.
                    registry_extra_keys.with_display_paths(rows)
                    marks = ", ".join("?" * (len(columns) + 1))
                    sql = ("INSERT OR IGNORE INTO %s (%s, parsed_at) "
                           "VALUES (%s)"
                           % (table, ", ".join(columns), marks))
                    for row in rows:
                        cursor.execute(sql, tuple(row.get(c) for c in columns)
                                       + (_walk_stamp,))
                        _extra["n"] += cursor.rowcount if cursor.rowcount > 0 else 0

                _put("startup_approved",
                     ["hive", "scope", "entry_name", "state", "state_byte",
                      "disabled_at", "key_path"],
                     registry_extra_keys.startup_approved(
                         _vals, _subs, _sw(K["startup_approved_hklm"]), "HKLM")
                     + registry_extra_keys.startup_approved(
                         _vals, _subs, _nt(K["startup_approved_hkcu"]), "HKCU"))

                _put("app_paths",
                     ["app_name", "executable_path", "app_dir", "key_path"],
                     registry_extra_keys.app_paths(
                         _vals, _subs, _sw(K["app_paths"])))

                _put("safe_boot_services",
                     ["boot_mode", "entry_name", "entry_type", "key_path"],
                     registry_extra_keys.safe_boot_services(
                         _vals, _subs, _sys(K["safe_boot"])))

                _put("zone_map",
                     ["scope", "host", "protocol", "zone", "zone_name",
                      "key_path"],
                     registry_extra_keys.zone_map(
                         _vals, _subs, _nt(K["zone_map"])))

                _put("app_permissions",
                     ["capability", "app", "packaged", "permission",
                      "last_used_start", "last_used_stop", "key_path"],
                     registry_extra_keys.app_permissions(
                         _vals, _subs, _sw(K["consent_store"])))

                _put("shared_dlls",
                     ["dll_path", "reference_count", "key_path"],
                     registry_extra_keys.shared_dlls(
                         _vals, _sw(K["shared_dlls"])))

                _put("hid_devices",
                     ["device_id", "instance_id", "device_desc",
                      "manufacturer", "service", "key_path"],
                     registry_extra_keys.hid_devices(
                         _vals, _subs, _sys(K["hid"])))

                _put("network_cards",
                     ["card_index", "description", "service_name", "key_path"],
                     registry_extra_keys.network_cards(
                         _vals, _subs, _sw(K["network_cards"])))

                _put("system_configuration",
                     ["setting", "value_raw", "value_decoded", "area",
                      "meaning", "key_path"],
                     registry_extra_keys.system_configuration(_vals, _resolved))

                # SecurityPosture is guarded, not constrained - it predates
                # _put and declares no UNIQUE, so OR IGNORE has nothing to act
                # on and would append these five settings on every re-parse.
                # Adding a UNIQUE would not fix it either: CREATE TABLE IF NOT
                # EXISTS leaves every case already on disk without one. So the
                # guard goes here, the way the other nine writers do it.
                _sp_cols = ["setting", "value_raw", "value_decoded",
                            "default_value", "assessment", "meaning",
                            "key_path"]
                for _row in registry_extra_keys.with_display_paths(
                        registry_extra_keys.security_posture(_vals, _resolved)):
                    if check_exists(cursor, "SecurityPosture",
                                    ["setting", "key_path"],
                                    (_row.get("setting"),
                                     _row.get("key_path"))):
                        continue
                    cursor.execute(
                        "INSERT INTO SecurityPosture (%s, parsed_at) "
                        "VALUES (%s)"
                        % (", ".join(_sp_cols), ", ".join("?" * (len(_sp_cols) + 1))),
                        tuple(_row.get(c) for c in _sp_cols) + (_walk_stamp,))
                    _extra["n"] += 1

                # A Run value is a request; StartupApproved is the answer.
                # A row with no approval entry stays "unknown", never
                # "enabled" - most autostart locations have no equivalent.
                cursor.execute("UPDATE AutoStartPrograms SET startup_state = "
                               "'unknown' WHERE startup_state IS NULL")
                _marked = 0
                for _st, _at, _nm, _sc in cursor.execute(
                        "SELECT state, disabled_at, entry_name, scope "
                        "FROM startup_approved").fetchall():
                    _like = "%" + str(_sc).replace("StartupFolder",
                                                   "Startup") + "%"
                    cursor.execute(
                        "UPDATE AutoStartPrograms SET startup_state = ?, "
                        "disabled_at = ? WHERE program_name = ? "
                        "AND location LIKE ?",
                        (_st, _at or "", _nm, _like))
                    _marked += cursor.rowcount if cursor.rowcount > 0 else 0
                conn.commit()

                _dis = cursor.execute(
                    "SELECT COUNT(*) FROM startup_approved "
                    "WHERE state = 'disabled'").fetchone()[0]
                print("[OK] Previously unread keys: %d rows" % _extra["n"])
                if _dis:
                    print("     %d autostart entr%s disabled; %d row(s) in "
                          "AutoStartPrograms carry their real state"
                          % (_dis, "y is" if _dis == 1 else "ies are", _marked))
            except Exception as _exc:
                logging.debug("extra key pass: %s", _exc)

            # ---- which value each pending transaction changed --------
            # A key records when it was last written; its values record
            # nothing, so this is the only place that says WHICH value moved.
            # The acquired copy is the state BEFORE the pending transactions
            # and the logs beside it hold the state after, so the bytes that
            # differ name the value. Diffing a replayed copy instead makes both
            # sides identical and finds nothing at all.
            _changes = 0
            _change_hives = 0
            _key_rows = 0
            _key_time = {}
            try:
                _change_hives = len({_l for _l, _ in _pending_changes})
                for _label, _r in _pending_changes:
                    _ca = _fmt_ft(_r.get("changed_at_raw"))
                    _kw = _fmt_ft(_r.get("key_last_write_raw"))
                    cursor.execute(
                        'INSERT OR IGNORE INTO registry_value_changes ('
                        'hive_name, transaction_sequence, change_kind, '
                        'changed_at, key_path, value_name, value_type, '
                        'changed_before, changed_after, value_before, '
                        'changed_bytes, cell_offset, key_last_write, '
                        'parsed_at) '
                        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        (_label, _r["sequence"], _r["change_kind"], _ca,
                         _r["key_path"], _r["value_name"],
                         _REG_TYPE_NAMES.get(_r.get("value_type"), "UNKNOWN"),
                         _r["changed_before"], _r["changed_after"],
                         _r["value_before"], _r["changed_bytes"],
                         _r["offset"], _kw, _walk_stamp))
                    _changes += cursor.rowcount if cursor.rowcount > 0 else 0

                for _label, _kt in _pending_keytimes:
                    _when = _fmt_ft(_kt["timestamp_raw"])
                    if not _when:
                        continue
                    _nk = _norm_key(_kt["key_path"])
                    _prev = _key_time.get(_nk)
                    # Where two hives spell the same path, take the LATEST.
                    # An upper bound that is too late is still true; one
                    # that is too early is a false claim.
                    if _prev is None or _when > _prev[2]:
                        _key_time[_nk] = (_label, _kt["key_path"], _when,
                                          _kt["cell_offset"])
                conn.commit()
            except Exception as _exc:
                logging.debug("live value change pass: %s", _exc)

            # ---- key times, and the bound they give every value row ----
            try:
                _wanted = set()
                for _t, _kc in _key_columns(cursor):
                    try:
                        for (_kp,) in cursor.execute(
                                "SELECT DISTINCT [%s] FROM [%s]" % (_kc, _t)):
                            if _kp:
                                _wanted.add(_norm_key(_kp))
                    except Exception:
                        continue
                for _nk in _wanted:
                    _hit = _key_time.get(_nk)
                    if not _hit:
                        continue
                    cursor.execute(
                        'INSERT OR IGNORE INTO registry_key_times (hive_name, '
                        'key_path, key_last_write, cell_offset, parsed_at) '
                        'VALUES (?, ?, ?, ?, ?)',
                        (_hit[0], _hit[1], _hit[2], _hit[3], _walk_stamp))
                    _key_rows += cursor.rowcount if cursor.rowcount > 0 else 0

                _exact = {}
                try:
                    for _kp, _vn, _at in cursor.execute(
                            'SELECT key_path, value_name, changed_at FROM '
                            'registry_value_changes WHERE changed_at IS NOT NULL '
                            'AND changed_at <> ""').fetchall():
                        _exact.setdefault((_norm_key(_kp), (_vn or "").lower()), _at)
                except Exception:
                    pass

                _timed = {"exact": 0, "bound": 0, "none": 0}
                for _tbl, _kc in _key_columns(cursor):
                    cursor.execute("PRAGMA table_info([%s])" % _tbl)
                    _cols = [r[1] for r in cursor.fetchall()]
                    _vc = next((c for c in ("value_name", "name", "program_name")
                                if c in _cols), None)
                    _sel = "SELECT rowid, [%s]%s FROM [%s]" % (
                        _kc, (", [%s]" % _vc) if _vc else "", _tbl)
                    _updates = []
                    for _row in cursor.execute(_sel).fetchall():
                        _rid, _kp = _row[0], _row[1]
                        _vn = (_row[2] if _vc and len(_row) > 2 else "") or ""
                        _nk = _norm_key(_kp)
                        if not _nk:
                            _timed["none"] += 1
                            continue
                        _hit = _exact.get((_nk, _vn.lower()))
                        if _hit:
                            _updates.append((_hit, "value (txn log)", _rid))
                            _timed["exact"] += 1
                            continue
                        _bound = _key_time.get(_nk)
                        if _bound:
                            _updates.append((_bound[2], "key upper bound", _rid))
                            _timed["bound"] += 1
                        else:
                            _timed["none"] += 1
                    if _updates:
                        cursor.executemany(
                            "UPDATE [%s] SET last_written = ?, time_basis = ? "
                            "WHERE rowid = ?" % _tbl, _updates)
                conn.commit()
                print("[OK] Value changes from transaction logs: %d across %d "
                      "hive(s)" % (_changes, _change_hives))
                print("[OK] Key times: %d keys; value rows dated: %d exact, "
                      "%d bounded, %d without a key"
                      % (_key_rows, _timed["exact"], _timed["bound"],
                         _timed["none"]))
            except Exception as _exc:
                logging.debug("live time basis pass: %s", _exc)

            conn.commit()
            _routes = ", ".join("%s=%s" % (k, v) for k, v in sorted(_hive_routes.items()))
            print("[OK] Hive structure: %d class names, %d security descriptors, "
                  "%d carved keys, %d carved values" %
                  (_tot["c"], _tot["s"], _tot["k"], _tot["v"]))
            print("     acquired by: %s" % _routes)
        except Exception as e:
            logging.error("Error walking acquired hives: %s", e)
            print("Warning: hive structure walk did not complete: %s" % e)

        # One row per hive saying HOW it was read. A carved table that is empty
        # means "nothing was deleted" after a file route and "this route cannot
        # see deletions" after an export, and an analyst cannot tell the two
        # apart without this.
        try:
            _hs_stamp = format_forensic_timestamp(get_current_utc())
            for _label, _route in sorted(_hive_routes.items()):
                # registry_hive_state carries no UNIQUE constraint, so OR IGNORE
                # would be a no-op and re-parsing the same machine would append
                # these rows again. Keyed on the hive and the route it came by:
                # a second parse that used a different route is a new fact and
                # gets its own row.
                if check_exists(cursor, 'registry_hive_state',
                                ['hive_name', 'acquisition_route'],
                                (_label, _route)):
                    continue
                cursor.execute(
                    'INSERT INTO registry_hive_state (hive_name, hive_path, '
                    'sequence_1, sequence_2, was_dirty, logs_found, log_format, '
                    'replayed, entries_applied, pages_applied, highest_sequence, '
                    'source_sha256, acquisition_route, reason, parsed_at) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (_label, "", None, None, None, "", "", 0, 0, 0, None, "",
                     _route,
                     "live parse: the running registry is the state, so there is "
                     "no hive file to be mid-transaction", _hs_stamp))
            conn.commit()
        except Exception as e:
            logging.error("Could not record acquisition routes: %s", e)


        # Commit the transaction
        conn.commit()
        print(f"Registry data collection complete. Data saved to {db_filename}")
        return db_filename
        
    except Exception as e:
        error_msg = f"Critical error in registry parsing: {str(e)}"
        logging.error(error_msg)
        print(f"[Registry Error] {error_msg}")
        # Return the database path even on error - partial data may have been collected
        return db_filename
if __name__ == "__main__":
    main_live_reg()
