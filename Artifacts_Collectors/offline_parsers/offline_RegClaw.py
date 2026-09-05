"""
COMPREHENSIVE OFFLINE FORENSIC REGISTRY ANALYSIS TOOL
=====================================================
Enhanced offline registry collection with binary parsing and malware detection

Capabilities:
- 40+ forensic tables across 20+ artifact types
- 100+ data fields from 55+ registry paths
- USB device timeline with serial tracking
- Malware detection and risk scoring
- Complete user activity reconstruction
- Network location history
- Browser and software inventory
- System event timeline
- Full forensic analysis capability without live system access

Supported Registry Hives:
- SYSTEM: System configuration and hardware information
- SOFTWARE: Installed software and system-wide settings
- NTUSER.DAT: Per-user settings and Desktop/Network ShellBags
- UsrClass.dat: Per-user Windows Explorer ShellBags and file associations

Note: Both NTUSER.DAT and UsrClass.dat are required for complete ShellBags
      analysis. UsrClass.dat contains the majority of Windows Explorer folder
      access history.

"""

import hashlib
import sqlite3
import os
import re
import datetime
import logging
import struct
import shutil
import tempfile
from Registry import Registry

# Import registry_binary_parser with fallback
try:
    from Artifacts_Collectors import registry_binary_parser
except ModuleNotFoundError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from Artifacts_Collectors import registry_binary_parser

# Transaction-log replay, so a hive Windows had open is not read as final, and
# the allocator walk, which reaches what a tree walk cannot: class names, the
# shared security descriptors, and records still sitting in freed cells.
try:
    from Artifacts_Collectors import registry_transaction_log
    from Artifacts_Collectors import registry_hive_walk
    from Artifacts_Collectors import registry_extra_keys
except ModuleNotFoundError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from Artifacts_Collectors import registry_transaction_log
    from Artifacts_Collectors import registry_hive_walk
    from Artifacts_Collectors import registry_extra_keys

# Shared with the live parser so both produce the same accounts and the same
# user names - see Artifacts_Collectors/user_identity.py
try:
    from Artifacts_Collectors import user_identity
except ModuleNotFoundError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from Artifacts_Collectors import user_identity

# Also shared with the live parser - LSA policy, audit policy and secret
# metadata from the SECURITY hive.
try:
    from Artifacts_Collectors import security_hive
except ModuleNotFoundError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from Artifacts_Collectors import security_hive

# Import PathUtils for Linux compatibility
try:
    from utils.path_utils import PathUtils
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.path_utils import PathUtils

# Import time_utils for standardized forensic timestamp formatting
try:
    from utils.time_utils import format_forensic_timestamp, get_current_utc, get_current_forensic_timestamp, filetime_to_datetime
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.time_utils import format_forensic_timestamp, get_current_utc, get_current_forensic_timestamp, filetime_to_datetime


# ============================================================================
# PHASE 1: UTILITY FUNCTIONS & HELPERS
# ============================================================================

def _configure_logging(log_file='offline_regclaw_errors.log'):
    """Configure logging with fallback for low disk space."""
    import shutil
    try:
        usage = shutil.disk_usage(os.getcwd())
        free = usage.free
    except Exception:
        free = 0

    if free < 5 * 1024 * 1024:
        logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')
    else:
        logging.basicConfig(
            filename=log_file,
            level=logging.ERROR,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )


def format_focus_time(milliseconds):
    """Convert milliseconds to human-readable format."""
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


def _off_decoded(table, name, data, vtype=None, env=None):
    """The decoded form of a plain value, or "".

    Module level because the two tables that use it are written deep
    inside the parse, well before the ASEP environment is built.

    `env` is empty by default, so %VARIABLE% values in these two
    tables are left standing offline rather than expanded against the
    examiner's own machine. Switches, locales and flag fields do not
    depend on an environment and decode either way.
    """
    try:
        got = registry_binary_parser.render_registry_value(
            table, name, data, vtype, env) or ""
    except Exception:
        return ""
    return "" if got == str(data) else got


def check_exists(cursor, table_name, conditions, values):
    """Check if record exists in table.

    `IS`, not `=`: SQL equality against NULL is never true, so a guard including
    a column that is legitimately NULL would never match and every re-parse
    would append the rows again. `IS` is NULL-safe and matches `=` otherwise.
    Kept identical to the live parser's copy.
    """
    try:
        query = f"SELECT 1 FROM {table_name} WHERE {' AND '.join(f'{col} IS ?' for col in conditions)}"
        cursor.execute(query, values)
        return cursor.fetchone() is not None
    except Exception as e:
        logging.error(f"Error checking existence in {table_name}: {e}")
        return False


def _extract_sid_from_path(subkey_path):
    """Extract Windows SID from registry path."""
    try:
        parts = subkey_path.split('\\')
        for part in parts:
            if part.startswith('S-1-5-'):
                return part
        return parts[-1] if parts else ''
    except Exception:
        return ''



# The documented value types, for naming a carved value's type. A carved cell
# can hold anything, including a type outside this set, which is exactly why
# the lookup has a default rather than raising.
_REG_TYPE_NAMES = {
    0: "REG_NONE", 1: "REG_SZ", 2: "REG_EXPAND_SZ", 3: "REG_BINARY",
    4: "REG_DWORD", 5: "REG_DWORD_BIG_ENDIAN", 6: "REG_LINK",
    7: "REG_MULTI_SZ", 8: "REG_RESOURCE_LIST",
    9: "REG_FULL_RESOURCE_DESCRIPTOR", 10: "REG_RESOURCE_REQUIREMENTS_LIST",
    11: "REG_QWORD",
}



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


def _value_bytes(value):
    """Read a value's data, even when its type is not one Windows documents.

    python-registry raises UnknownTypeException from .value() for any type
    outside the documented twelve. Device and driver keys are full of them:
    Enum, DeviceClasses and DriverDatabase store Plug and Play device property
    types in the same field, and those types are not in the REG_* set.

    Left uncaught this is expensive out of all proportion, because the read
    loops sit inside a try that covers the whole key: one odd value discarded
    every value in that key and the log blamed a missing path. Measured on a
    real SYSTEM hive that was 1,319 keys, 254 of them under Enum\\USB, which
    is USB device history.

    Returns (data, ok). ok is False when the type had to be bypassed, so the
    caller can label the type UNKNOWN rather than claim to know it.
    """
    try:
        return value.value(), True
    except Exception:
        # The bytes are still there; only the interpretation is unavailable.
        try:
            return value.raw_data(), False
        except Exception:
            return None, False


def _device_property_time(values):
    """Turn a device property key's value into a forensic timestamp.

    The properties under {83da6326-97a6-4088-9453-a1923f573b29} are
    DEVPROP_TYPE_FILETIME, which is not a REG_* type. python-registry knows
    that one and hands back a datetime; other readers hand back the raw eight
    bytes. Both arrive here, and a reader that accepted only bytes produced an
    empty column on every device.
    """
    for _name, _entry in (values or {}).items():
        d = _entry[0] if isinstance(_entry, tuple) else _entry
        if isinstance(d, datetime.datetime):
            return format_forensic_timestamp(d)
        if isinstance(d, bytes) and len(d) >= 8:
            try:
                return format_forensic_timestamp(
                    filetime_to_datetime(int.from_bytes(d[:8], byteorder="little")))
            except Exception:
                continue
    return ""


def _default_name(name):
    """Normalise a value name so offline rows match the live parser's.

    winreg reports a key's default value as an empty name; python-registry
    reports it as the literal string "(default)", lowercase. The live parser
    writes "(Default)", and several places compare against exactly that to
    decide whether to roll a row up into AutoStartPrograms. Left unnormalised
    the comparison silently never matches offline, so the same hive yields a
    different AutoStartPrograms depending on how it was acquired - with no
    error to notice.
    """
    if not name or str(name).lower() == "(default)":
        return "(Default)"
    return name


def _extract_usbstor(device_class):
    """Extract vendor/product/revision from USBSTOR device class.
    Format: Disk&Ven_Samsung&Prod_USB3.0&Rev_1100
    """
    try:
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
        return vendor_id, product_id, revision
    except Exception as e:
        logging.error(f"Error extracting USBSTOR: {e}")
        return "", "", ""


def _is_suspicious_path(path_str):
    """Check if execution path shows suspicious indicators."""
    if not path_str:
        return False
    path_lower = path_str.lower()
    suspicious_indicators = [
        'temp\\', 'tmp\\', '%temp%', 'appdata\\local\\temp',
        '\\windows\\',
        'system32', 'syswow64',
        '.zip', '.rar', '.7z',
        '.vbs', '.ps1', '.cmd', '.bat'
    ]
    return any(indicator in path_lower for indicator in suspicious_indicators)


def _malware_keywords():
    """List of known hacking/malware tools for detection."""
    return [
        'mimikatz', 'hashcat', 'aircrack', 'cain', 'abel',
        'wce', 'pwdump', 'lsass', 'backdoor', 'rootkit',
        'meterpreter', 'psexec', 'procdump', 'comsvcs',
        'vcab', 'vmcompute', 'sdelete', 'psloggedon',
        'putty', 'plink', 'netcat', 'nc.exe', 'socat',
        'nmap', 'masscan', 'hping3', 'nuclei', 'metasploit',
        'cobalt', 'beacon', 'empire', 'powershell_empire',
        'evasion', 'obfuscation', 'crypter', 'packer',
        'kali', 'parrot', 'pentoo', 'wifite', 'hashkill'
    ]


def _get_risk_level(severity):
    """Convert numeric severity to risk level."""
    severity_map = {5: 'CRITICAL', 4: 'HIGH', 3: 'MEDIUM', 2: 'LOW', 1: 'INFO'}
    return severity_map.get(severity, 'UNKNOWN')


def detect_hive_files(registry_dir):
    r"""
    Detect registry hive files with flexible naming conventions.
    
    Handles:
    - Files without extensions: SYSTEM, SOFTWARE, SAM, SECURITY
    - Files with .DAT extension: NTUSER.DAT, UsrClass.dat
    - Files with backup extensions: .OLD, .SAV, .BAK
    - Case-insensitive matching
    
    Args:
        registry_dir: Directory containing registry hive files
    
    Returns:
        dict: {hive_type: full_path} for detected hives
        
    Example:
        {'system': '/path/to/SYSTEM', 
         'ntuser': ['/path/to/NTUSER.DAT', '/path/to/user2/NTUSER.DAT'],
         'usrclass': ['/path/to/UsrClass.dat', '/path/to/user2/UsrClass.dat']}
    
    Note:
        - NTUSER and UsrClass hives return lists (multiple users supported)
        - Other hives return single path string
        - UsrClass.dat contains Windows Explorer ShellBags data
        - UsrClass.dat is typically located at: Users\<USERNAME>\AppData\Local\Microsoft\Windows\UsrClass.dat
    """
    hive_patterns = {
        'system': ['SYSTEM', 'system', 'System', 'SYSTEM.OLD', 'system.old', 
                   'SYSTEM.SAV', 'system.sav', 'SYSTEM.BAK', 'system.bak'],
        'software': ['SOFTWARE', 'software', 'Software', 'SOFTWARE.OLD', 'software.old',
                     'SOFTWARE.SAV', 'software.sav', 'SOFTWARE.BAK', 'software.bak'],
        'sam': ['SAM', 'sam', 'Sam', 'SAM.OLD', 'sam.old', 
                'SAM.SAV', 'sam.sav', 'SAM.BAK', 'sam.bak'],
        'security': ['SECURITY', 'security', 'Security', 'SECURITY.OLD', 'security.old',
                     'SECURITY.SAV', 'security.sav', 'SECURITY.BAK', 'security.bak'],
        'ntuser': ['NTUSER_copy.DAT', 'ntuser_copy.dat', 'Ntuser_copy.dat',
                   'NTUSER.DAT', 'ntuser.dat', 'Ntuser.dat', 'NTUSER', 'ntuser', 'Ntuser',
                   'NTUSER.OLD', 'ntuser.old', 'NTUSER.SAV', 'ntuser.sav'],
        'usrclass': ['UsrClass.dat', 'USRCLASS.DAT', 'usrclass.dat', 'UsrClass', 
                     'USRCLASS', 'usrclass', 'UsrClass.OLD', 'usrclass.old', 
                     'UsrClass.SAV', 'usrclass.sav', 'UsrClass.BAK', 'usrclass.bak'],
        # HKU\.DEFAULT lives in this hive. It is the profile that applies before
        # anyone logs on, which makes it a persistence location worth reading,
        # and nothing has ever collected or parsed it.
        'default': ['DEFAULT', 'default', 'Default', 'DEFAULT.OLD', 'default.old',
                    'DEFAULT.SAV', 'default.sav', 'DEFAULT.BAK', 'default.bak'],
    }
    
    detected_hives = {}
    
    # Check if registry_dir exists
    if not os.path.exists(registry_dir):
        logging.warning(f"Registry directory not found: {registry_dir}")
        return detected_hives
    
    # Try to detect each hive type - collect ALL matching files for ntuser/usrclass
    for hive_type, patterns in hive_patterns.items():
        # For ntuser and usrclass, we want to collect ALL matching files
        if hive_type in ['ntuser', 'usrclass']:
            # Every user's hive is collected under the same base name
            # (the collector globs {PARTITION}\Users\*\NTUSER.DAT), so a flat
            # exact-name lookup can only ever find one of them: on Windows
            # os.path.exists is case-insensitive, making NTUSER.DAT / ntuser.dat
            # / Ntuser.dat / NTUSER the same file. That silently capped offline
            # parsing at a single user.
            #
            # Match by stem instead, and walk subdirectories, so per-user copies
            # survive whatever disambiguation the collector applied
            # (NTUSER_1.DAT, NTUSER_ghass.DAT, Users\<name>\NTUSER.DAT).
            stem = hive_type            # 'ntuser' / 'usrclass'
            exts = ('.dat', '.old', '.sav', '.bak')

            def _is_hive(fname):
                low = fname.lower()
                if not low.startswith(stem):
                    return False
                rest = low[len(stem):]
                if rest == '':
                    return True                       # bare "NTUSER"
                if not rest.startswith(('.', '_', '-')):
                    return False                      # "ntuserfoo.dat" is not one
                return rest.endswith(exts)

            matching_files = []
            for root, _dirs, files in os.walk(registry_dir):
                for fname in files:
                    if _is_hive(fname):
                        full = os.path.join(root, fname)
                        matching_files.append(full)
                        logging.info(f"Detected {hive_type} hive: {full}")


            # Store ALL matching files as a list (not just one)
            if matching_files:
                # Deduplicate by normalizing paths (case-insensitive on Windows)
                unique_files = []
                seen_paths = set()
                for f in matching_files:
                    normalized = os.path.normcase(os.path.normpath(f))
                    if normalized not in seen_paths:
                        seen_paths.add(normalized)
                        unique_files.append(f)
                
                detected_hives[hive_type] = unique_files
                if len(unique_files) > 1:
                    logging.info(f"Multiple {hive_type} files found ({len(unique_files)}), will parse all")
        else:
            # For other hive types, use first match
            for pattern in patterns:
                hive_path = os.path.join(registry_dir, pattern)
                if os.path.exists(hive_path) and os.path.isfile(hive_path):
                    detected_hives[hive_type] = hive_path
                    logging.info(f"Detected {hive_type} hive: {hive_path}")
                    break  # Found this hive type, move to next
    
    return detected_hives


def validate_hive_file(hive_path, hive_type=''):
    """
    Validate registry hive file for security and format checks.
    
    Performs:
    - File existence check
    - File readability check
    - File size validation (not empty, reasonable size)
    - Registry hive format validation using python-registry
    
    Args:
        hive_path: Path to registry hive file
        hive_type: Optional hive type name for error messages (e.g., 'SYSTEM', 'NTUSER')
    
    Returns:
        tuple: (is_valid: bool, error_message: str)
        
    Example:
        is_valid, error = validate_hive_file('/path/to/SYSTEM', 'SYSTEM')
        if not is_valid:
            print(f"Validation failed: {error}")
    
    Requirements: 3.5, 4.2
    """
    hive_label = f"{hive_type} hive" if hive_type else "Registry hive"
    
    # Check 1: File existence
    if not hive_path:
        return False, f"{hive_label}: No path provided"
    
    if not os.path.exists(hive_path):
        return False, f"{hive_label}: File not found at '{hive_path}'"
    
    if not os.path.isfile(hive_path):
        return False, f"{hive_label}: Path exists but is not a file: '{hive_path}'"
    
    # Check 2: File readability
    if not os.access(hive_path, os.R_OK):
        return False, f"{hive_label}: File exists but is not readable (permission denied): '{hive_path}'"
    
    # Check 3: File size validation
    try:
        file_size = os.path.getsize(hive_path)
    except OSError as e:
        return False, f"{hive_label}: Cannot determine file size: {e}"
    
    # Check if file is empty
    if file_size == 0:
        return False, f"{hive_label}: File is empty (0 bytes): '{hive_path}'"
    
    # Check if file is too small (registry hives have minimum structure)
    MIN_HIVE_SIZE = 4096  # Registry hives have at least one 4KB page
    if file_size < MIN_HIVE_SIZE:
        return False, f"{hive_label}: File too small ({file_size} bytes, minimum {MIN_HIVE_SIZE}): '{hive_path}'"
    
    # Warn if file is very large (but don't fail)
    MAX_HIVE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB warning threshold
    if file_size > MAX_HIVE_SIZE:
        logging.warning(f"{hive_label}: Large file detected ({file_size / (1024*1024):.1f} MB): '{hive_path}'")
    
    # Check 4: Validate registry hive format using python-registry
    try:
        reg = Registry.Registry(hive_path)
        # Try to access the root key to verify it's a valid hive
        root = reg.root()
        # Verify root has a name (basic sanity check)
        if not hasattr(root, 'name'):
            return False, f"{hive_label}: Invalid registry structure (no root name): '{hive_path}'"
    except Registry.RegistryParse.ParseException as e:
        return False, f"{hive_label}: Invalid registry hive format (parse error): {e}"
    except Exception as e:
        return False, f"{hive_label}: Cannot open as registry hive: {e}"
    
    # All checks passed
    return True, ""


# ============================================================================
# CONTROLSET RESOLUTION HELPER FUNCTIONS
# ============================================================================

def check_hive_dirty(hive_path):
    """Report whether a hive was closed cleanly, from its header.

    A registry hive header carries two sequence numbers, at 0x04 and 0x08. They
    match when the hive was flushed cleanly. When they differ, Windows was
    mid-write and the outstanding changes live in the .LOG1/.LOG2 transaction
    logs - so the hive on disk is NOT the final state of the registry.

    python-registry does not replay those logs, so this cannot fix the data; it
    exists so a stale parse is stated rather than silent. Live-acquired images
    routinely land here (both hives in the LoneWolf reference image do).

    Returns (is_dirty, primary, secondary), or (None, None, None) if unreadable.
    """
    try:
        with open(hive_path, 'rb') as f:
            header = f.read(0x10)
        if len(header) < 0x0C or header[:4] != b'regf':
            return (None, None, None)
        primary, secondary = struct.unpack_from('<II', header, 0x04)
        return (primary != secondary, primary, secondary)
    except Exception as e:
        logging.debug(f"Could not read hive header for {hive_path}: {e}")
        return (None, None, None)


def get_active_controlset(system_hive):
    r"""
    Detect the active ControlSet from SYSTEM\Select\Current value.
    
    Args:
        system_hive: Path to SYSTEM registry hive file
    
    Returns:
        str: Active ControlSet name (e.g., "ControlSet001", "ControlSet002", "ControlSet003")
             Defaults to "ControlSet001" if detection fails
    
    Example:
        active_cs = get_active_controlset("/path/to/SYSTEM")
        # Returns: "ControlSet002"
    
    Requirements: 2.14, 2.17, 2.24, 2.25
    """
    try:
        reg = Registry.Registry(system_hive)
        select_key = reg.open("Select")
        
        # Read the Current value
        for value in select_key.values():
            if value.name() == "Current":
                current_value = value.value()
                controlset_name = f"ControlSet{current_value:03d}"
                logging.debug(f"Detected active ControlSet: {controlset_name}")
                return controlset_name
        
        # If Current value not found, fallback to ControlSet001
        logging.warning("SYSTEM\\Select\\Current value not found, defaulting to ControlSet001")
        return "ControlSet001"
    
    except Exception as e:
        logging.warning(f"Error detecting active ControlSet: {e}, defaulting to ControlSet001")
        return "ControlSet001"


def read_registry_multi_path(hive, base_path, controlset_dependent=True, active_controlset=None):
    """
    Read registry values from multiple possible paths with ControlSet fallback logic.
    
    This function implements the core fix for the hardcoded ControlSet001 bug.
    It tries multiple ControlSet paths and merges data from all successful reads.
    
    Args:
        hive: Path to registry hive file
        base_path: Base registry path (e.g., "Control\\ComputerName\\ComputerName")
        controlset_dependent: If True, prepend ControlSet paths; if False, use base_path as-is
        active_controlset: Active ControlSet name (e.g., "ControlSet002")
    
    Returns:
        tuple: (merged_values: dict, successful_paths: list)
               merged_values: Dictionary of {value_name: (value_data, value_type)}
               successful_paths: List of paths that successfully returned data
    
    Example:
        values, paths = read_registry_multi_path(
            system_hive,
            "Control\\ComputerName\\ComputerName",
            controlset_dependent=True,
            active_controlset="ControlSet002"
        )
        # Returns: ({'ComputerName': ('TEST-PC', 'REG_SZ')}, ['ControlSet002\\Control\\ComputerName\\ComputerName'])
    
    Requirements: 2.14, 2.18, 2.22, 2.23, 2.24, 2.25
    """
    merged_values = {}
    successful_paths = []
    
    # Build list of paths to try
    if controlset_dependent:
        # Try paths in order: active ControlSet -> CurrentControlSet -> ControlSet001 -> ControlSet002 -> ControlSet003
        paths_to_try = []
        
        # 1. Active ControlSet (highest priority)
        if active_controlset:
            paths_to_try.append(f"{active_controlset}\\{base_path}")
        
        # 2. CurrentControlSet (symbolic link, may not work in offline mode)
        paths_to_try.append(f"CurrentControlSet\\{base_path}")
        
        # 3. All possible ControlSets (fallback)
        for cs_num in [1, 2, 3]:
            cs_name = f"ControlSet{cs_num:03d}"
            if cs_name != active_controlset:  # Don't duplicate active ControlSet
                paths_to_try.append(f"{cs_name}\\{base_path}")
    else:
        # Non-ControlSet path, use as-is
        paths_to_try = [base_path]
    
    # Try each path and collect data
    for path in paths_to_try:
        try:
            logging.debug(f"Checking path: {path}")
            reg = Registry.Registry(hive)
            key = reg.open(path)
            
            # Read all values from this path
            path_values = {}
            for value in key.values():
                name = value.name()
                data, typed = _value_bytes(value)
                value_type = value.value_type()
                value_type_str = {
                    Registry.RegBin: "REG_BINARY",
                    Registry.RegSZ: "REG_SZ",
                    Registry.RegExpandSZ: "REG_EXPAND_SZ",
                    Registry.RegDWord: "REG_DWORD",
                    Registry.RegQWord: "REG_QWORD",
                    Registry.RegMultiSZ: "REG_MULTI_SZ",
                    Registry.RegNone: "REG_NONE"
                }.get(value_type, "UNKNOWN")
                if not typed:
                    value_type_str = "UNKNOWN"
                path_values[name] = (data, value_type_str)
            
            if path_values:
                logging.debug(f"Successfully read from: {path}")
                successful_paths.append(path)
                
                # Merge values (prefer values from earlier paths, i.e., active ControlSet)
                for name, value_tuple in path_values.items():
                    if name not in merged_values:
                        merged_values[name] = value_tuple
        
        except Exception as e:
            # Not necessarily missing: say what actually happened, because
            # "Path not found" sent an earlier investigation the wrong way.
            logging.debug(f"Could not read {path}: {type(e).__name__}: {e}")
            continue
    
    # Log summary
    if successful_paths:
        logging.debug(f"Extracted {len(merged_values)} values from {len(successful_paths)} path(s): {successful_paths}")
    else:
        logging.debug(f"No data found for base path: {base_path}")
    
    return merged_values, successful_paths


# ============================================================================
# MAIN REGISTRY COLLECTION FUNCTION
# ============================================================================

def reg_Claw(case_root=None, offline_mode=False, windows_partition="C:"):
    """
    Enhanced comprehensive offline registry collection with 40+ forensic tables.
    """
    _configure_logging()
    print("=" * 80)
    print("COMPREHENSIVE OFFLINE FORENSIC REGISTRY ANALYSIS")
    print("=" * 80)
    print("Starting enhanced registry collection with 20+ artifact types...\n")

    # Declared at function scope: the replay only runs on the offline path, but
    # registry_hive_state is written at the end regardless, and a name bound
    # inside an `if` is not a name that exists.
    _hive_states = []

    # Define paths
    if offline_mode and case_root:
        # Try multiple possible registry directory locations
        possible_registry_dirs = [
            os.path.join(case_root, "Target_Artifacts", "Registry_Hives"),
            os.path.join(case_root, "live_acquisition", "registry"),
            os.path.join(case_root, "live_acquisition", "Registry"),
            os.path.join(case_root, "live_acquisition", "Registry_Hives"),
        ]
        
        registry_dir = None
        detected_hives = {}
        
        print(f"[Offline Mode] Case Root: {case_root}")
        print(f"[Offline Mode] Searching for registry hives...")
        
        # Try each possible directory
        for dir_path in possible_registry_dirs:
            if os.path.exists(dir_path):
                print(f"  Checking: {dir_path}")
                temp_hives = detect_hive_files(dir_path)
                if temp_hives:
                    registry_dir = dir_path
                    detected_hives = temp_hives
                    print(f"  [OK] Found hives in: {dir_path}")
                    break
                else:
                    print(f"  - No hives found")
        
        if not registry_dir:
            print(f"[ERROR] No registry directory with hives found")
            print(f"[ERROR] Searched locations:")
            for dir_path in possible_registry_dirs:
                print(f"  - {dir_path}")
            raise ValueError("No registry hives found in any expected location")
        
        print(f"[Offline Mode] Using Registry Directory: {registry_dir}")
        
        # Map detected hives to expected variables
        # ntuser can be a list of files or a single file
        ntuser_hives = detected_hives.get('ntuser', [])
        if not isinstance(ntuser_hives, list):
            ntuser_hives = [ntuser_hives] if ntuser_hives else []
        
        # usrclass can be a list of files or a single file
        usrclass_hives = detected_hives.get('usrclass', [])
        if not isinstance(usrclass_hives, list):
            usrclass_hives = [usrclass_hives] if usrclass_hives else []
        
        system_reg_hive = detected_hives.get('system', '')
        Software_reg_hive = detected_hives.get('software', '')
        sam_reg_hive = detected_hives.get('sam', '')
        # detect_hive_files has always recognised SECURITY; nothing consumed it
        # until the LSA tables, so a collected SECURITY hive was silently unused.
        security_reg_hive = detected_hives.get('security', '')
        
        default_reg_hive = detected_hives.get('default', '')

        # ---------------------------------------------------------------- replay
        # A hive Windows had open is rarely the whole story: its outstanding
        # changes sit in the .LOG1/.LOG2 beside it. Recover into a temporary
        # copy and parse THAT, leaving the evidence untouched. Whatever happens
        # - recovered, no log collected, an old-format log - is recorded in
        # registry_hive_state and printed, because "this may not be the final
        # registry" is the analyst's call, not something to leave implicit.
        def _replay(path):
            """Recovered copy of `path`, or `path` unchanged. Never raises.

            The replay itself lives in registry_transaction_log, because five
            other parsers read these same hives and each of them needs the
            recovered state too. Going through the shared helper means SYSTEM
            is replayed once per run rather than once per parser.
            """
            if not path or not os.path.exists(path):
                return path
            resolved = registry_transaction_log.hive_for_reading(path)
            res = registry_transaction_log.recovery_result_for(path)
            if res is not None and res not in _hive_states:
                _hive_states.append(res)
                if res.recovered:
                    print("  [REPLAY] %s: %s" % (res.hive_name, res.reason))
                elif res.was_dirty:
                    # Loud on purpose. The rows about to be parsed may not be
                    # the final state of this registry.
                    print("  [STALE]  %s: dirty and NOT replayed - %s"
                          % (res.hive_name, res.reason))
            return resolved

        print("\n[Transaction Logs] Checking hives for outstanding transactions...")
        # Keep the pre-replay paths. Every other table describes the recovered
        # state, which is right - but the change pass needs the state BEFORE
        # the pending transactions, because that is the half of the diff the
        # log does not carry. Diff the recovered hive instead and the two sides
        # are identical by construction, so it finds nothing at all. That is
        # what the first run of this did: 259 changes where there were 4,000,
        # and no error anywhere.
        _pre_replay = {
            "SYSTEM": system_reg_hive, "SOFTWARE": Software_reg_hive,
            "SAM": sam_reg_hive, "SECURITY": security_reg_hive,
            "DEFAULT": default_reg_hive,
        }
        for _i, _h in enumerate(ntuser_hives or []):
            _pre_replay["NTUSER.DAT" if _i == 0 else "NTUSER.DAT[%d]" % _i] = _h
        for _i, _h in enumerate(usrclass_hives or []):
            _pre_replay["UsrClass.dat" if _i == 0 else "UsrClass.dat[%d]" % _i] = _h

        system_reg_hive = _replay(system_reg_hive)
        Software_reg_hive = _replay(Software_reg_hive)
        sam_reg_hive = _replay(sam_reg_hive)
        security_reg_hive = _replay(security_reg_hive)
        default_reg_hive = _replay(default_reg_hive)
        ntuser_hives = [_replay(h) for h in ntuser_hives]
        usrclass_hives = [_replay(h) for h in usrclass_hives]

        # Report detected hives
        if detected_hives:
            print(f"\n[Detected Hives] Found hive types:")
            for hive_type, hive_path in detected_hives.items():
                if isinstance(hive_path, list):
                    print(f"  - {hive_type.upper()}: {len(hive_path)} file(s)")
                    for path in hive_path:
                        print(f"      {os.path.basename(path)}")
                else:
                    print(f"  - {hive_type.upper()}: {os.path.basename(hive_path)}")
        else:
            print("[WARNING] No registry hives detected in directory")
        
        # Validate detected hives
        print("\n[Validation] Validating detected hive files...")
        validation_errors = []
        for hive_type, hive_path in detected_hives.items():
            if isinstance(hive_path, list):
                # Validate each file in the list
                for idx, path in enumerate(hive_path):
                    is_valid, error_msg = validate_hive_file(path, f"{hive_type.upper()}[{idx}]")
                    if is_valid:
                        print(f"  [OK] {hive_type.upper()}[{idx}]: Valid ({os.path.basename(path)})")
                    else:
                        print(f"  [FAIL] {hive_type.upper()}[{idx}]: {error_msg}")
                        validation_errors.append(error_msg)
                        logging.error(f"Hive validation failed: {error_msg}")
            else:
                is_valid, error_msg = validate_hive_file(hive_path, hive_type.upper())
                if is_valid:
                    print(f"  [OK] {hive_type.upper()}: Valid")
                else:
                    print(f"  [FAIL] {hive_type.upper()}: {error_msg}")
                    validation_errors.append(error_msg)
                    logging.error(f"Hive validation failed: {error_msg}")
        
        if validation_errors:
            print(f"\n[ERROR] {len(validation_errors)} hive validation error(s) detected")
            print("[ERROR] Cannot proceed with invalid hive files")
            raise ValueError(f"Hive validation failed: {'; '.join(validation_errors)}")
        
        print("[Validation] All detected hives are valid\n")
        
        db_path = os.path.join(case_root, "Target_Artifacts", "registry_data.db")
        # Nothing else in the codebase creates Target_Artifacts, so a case that
        # has not been through the full GUI setup fails here with a bare
        # "unable to open database file" from sqlite. Create it rather than
        # depending on someone else having done so.
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
    else:
        system_root = os.getenv('SystemRoot', f'{windows_partition}\\Windows')
        user_profile = os.getenv('USERPROFILE', f'{windows_partition}\\Users\\Default')
        ntuser_hives = [os.path.join(user_profile, 'NTUSER.DAT')]
        usrclass_hives = []  # UsrClass.dat not typically used in live mode
        system_reg_hive = os.path.join(system_root, 'System32', 'config', 'SYSTEM')
        Software_reg_hive = os.path.join(system_root, 'System32', 'config', 'SOFTWARE')
        # SAM cannot be read in place on a running system (the file is locked and
        # the key is unreadable even elevated), so this path only finds it when a
        # collected copy is present.
        sam_reg_hive = os.path.join(system_root, 'System32', 'config', 'SAM')
        # SECURITY is locked in place for the same reason as SAM, so this path
        # only finds it when a collected copy is present.
        security_reg_hive = os.path.join(system_root, 'System32', 'config', 'SECURITY')
        if not all(os.path.exists(f) for f in ntuser_hives + [system_reg_hive, Software_reg_hive]):
            ntuser_hives = [r"Artifacts_Collectors\Target Artifacts\Registry Hives\NTUSER.DAT"]
            system_reg_hive = r"Artifacts_Collectors\Target Artifacts\Registry Hives\SYSTEM"
            Software_reg_hive = r"Artifacts_Collectors\Target Artifacts\Registry Hives\SOFTWARE"
            sam_reg_hive = r"Artifacts_Collectors\Target Artifacts\Registry Hives\SAM"
            security_reg_hive = r"Artifacts_Collectors\Target Artifacts\Registry Hives\SECURITY"
        db_path = 'registry_data.db'
        
        # Validate hives in non-offline mode
        print("\n[Validation] Validating hive files...")
        validation_errors = []
        for hive_name, hive_path in [('SYSTEM', system_reg_hive), ('SOFTWARE', Software_reg_hive)]:
            if hive_path and os.path.exists(hive_path):
                is_valid, error_msg = validate_hive_file(hive_path, hive_name)
                if is_valid:
                    print(f"  [OK] {hive_name}: Valid")
                else:
                    print(f"  [FAIL] {hive_name}: {error_msg}")
                    validation_errors.append(error_msg)
                    logging.error(f"Hive validation failed: {error_msg}")
        
        # Validate NTUSER hives
        for idx, ntuser_path in enumerate(ntuser_hives):
            if ntuser_path and os.path.exists(ntuser_path):
                hive_label = f"NTUSER[{idx}]" if len(ntuser_hives) > 1 else "NTUSER"
                is_valid, error_msg = validate_hive_file(ntuser_path, hive_label)
                if is_valid:
                    print(f"  [OK] {hive_label}: Valid")
                else:
                    print(f"  [FAIL] {hive_label}: {error_msg}")
                    validation_errors.append(error_msg)
                    logging.error(f"Hive validation failed: {error_msg}")
        
        if validation_errors:
            print(f"\n[ERROR] {len(validation_errors)} hive validation error(s) detected")
            raise ValueError(f"Hive validation failed: {'; '.join(validation_errors)}")
        
        print("[Validation] All hives are valid\n")

    # Validate required hives exist
    required_hives = {
        'NTUSER': ntuser_hives,
        'SYSTEM': system_reg_hive,
        'SOFTWARE': Software_reg_hive
    }
    
    # Check for missing hives
    missing_hives = []
    if not ntuser_hives:
        missing_hives.append('NTUSER')
    if not system_reg_hive or not os.path.exists(system_reg_hive):
        missing_hives.append('SYSTEM')
    if not Software_reg_hive or not os.path.exists(Software_reg_hive):
        missing_hives.append('SOFTWARE')
    
    if missing_hives:
        print(f"[ERROR] Missing required registry hives: {', '.join(missing_hives)}")
        if offline_mode:
            print(f"[ERROR] Please ensure hive files are in: {registry_dir}")
            print("[INFO] Supported file names (case-insensitive):")
            print("  - SYSTEM, SOFTWARE (no extension)")
            print("  - NTUSER.DAT or NTUSER")
            print("  - Backup extensions: .OLD, .SAV, .BAK")
        raise ValueError(f"Missing required registry hives: {', '.join(missing_hives)}")

    # Registry helper functions
    def read_registry_values(hive, key):
        """Read registry values from hive file."""
        try:
            reg = Registry.Registry(hive)
            key = reg.open(key)
            values = {}
            for value in key.values():
                name = value.name()
                data, typed = _value_bytes(value)
                value_type = value.value_type()
                value_type_str = {
                    Registry.RegBin: "REG_BINARY",
                    Registry.RegSZ: "REG_SZ",
                    Registry.RegExpandSZ: "REG_EXPAND_SZ",
                    Registry.RegDWord: "REG_DWORD",
                    Registry.RegQWord: "REG_QWORD",
                    Registry.RegMultiSZ: "REG_MULTI_SZ",
                    Registry.RegNone: "REG_NONE"
                }.get(value_type, "UNKNOWN")
                if not typed:
                    value_type_str = "UNKNOWN"
                values[name] = (data, value_type_str)
            return values
        except Exception as e:
            logging.debug(f"Error reading registry key: {e}")
            return {}

    def key_last_write(hive, key_path):
        """The key's own last-write time, formatted UTC, or '' if unreadable.

        For an MRU key this is the artifact's only timestamp: RecentDocs stores
        no per-value time, so the last write on `RecentDocs\\.pdf` is when a PDF
        was most recently opened. python-registry reads it straight off the NK
        record and returns naive UTC, which is what format_forensic_timestamp
        expects.
        """
        try:
            reg = Registry.Registry(hive)
            return format_forensic_timestamp(reg.open(key_path).timestamp())
        except Exception as e:
            logging.debug(f"No last-write time for {key_path}: {e}")
            return ""

    def get_subkeys(hive, key):
        """Get subkeys and their values from registry hive."""
        try:
            reg = Registry.Registry(hive)
            key = reg.open(key)
            subkey_values = {}
            for subkey in key.subkeys():
                subkey_values[subkey.name()] = {}
                for value in subkey.values():
                    name = value.name()
                    data, typed = _value_bytes(value)
                    value_type = value.value_type()
                    value_type_str = {
                        Registry.RegBin: "REG_BINARY",
                        Registry.RegSZ: "REG_SZ",
                        Registry.RegExpandSZ: "REG_EXPAND_SZ",
                        Registry.RegDWord: "REG_DWORD",
                        Registry.RegQWord: "REG_QWORD",
                        Registry.RegMultiSZ: "REG_MULTI_SZ",
                        Registry.RegNone: "REG_NONE"
                    }.get(value_type, "UNKNOWN")
                    if not typed:
                        value_type_str = "UNKNOWN"
                    subkey_values[subkey.name()][name] = (data, value_type_str)
            return subkey_values
        except Exception as e:
            logging.debug(f"Error reading subkeys: {e}")
            return {}

    # ========================================================================
    # CREATE DATABASE & TABLES
    # ========================================================================

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    print(f"[Database] Using: {db_path}")
    print("[Database] Creating 40+ forensic tables...\n")

    # Create comprehensive table set (40+ tables) - Phase 1-9
    tables_basic = [
        ("machine_run", "name TEXT, row_data TEXT, row_decoded TEXT, type TEXT"),
        ("machine_run_once", "name TEXT, row_data TEXT, type TEXT"),
        ("user_run", "name TEXT, row_data TEXT, type TEXT"),
        ("user_run_once", "name TEXT, row_data TEXT, type TEXT"),
        # 'data', not 'row_data': the inserts below name `data`, matching the
        # live schema. Declared as row_data every insert raised inside a
        # try/except and Network_list came out empty in EVERY offline case -
        # the same defect the comment below describes for computer_Name and
        # time_zone, which this table was missed out of. Found by diffing live
        # against offline per-table row counts: 52 rows live, 0 offline.
        # The four enrichment columns match the live schema. They were absent
        # here, so the same network profile carried different columns depending
        # on whether the case was acquired live or from an image.
        # is_hidden is gone from both parsers. It was derived from
        # NameType == 6, which is a WIRED network, and it was a verdict where
        # the registry only offers a fact.
        ("Network_list", "subkey TEXT, name TEXT, data TEXT, decoded TEXT, "
                         "type TEXT, network_name TEXT, connection_date TEXT, "
                         "gateway_mac TEXT, parsed_at TEXT"),
        # 'type' matches the live schema. Without it the inserts below - which
        # named a non-existent column - failed inside a try/except and left both
        # tables empty in every offline case.
        ("computer_Name", "name TEXT, row_data TEXT, type TEXT"),
        ("time_zone", "name TEXT, row_data TEXT, decoded TEXT, type TEXT"),
        # Raw layer for keys whose structured tables already exist here. The
        # live parser creates all four; offline created none, so the same
        # machine yielded a different schema depending on how it was acquired.
        ("network_interfaces", "subkey TEXT, name TEXT, row_data TEXT, decoded TEXT, type TEXT"),
        ("shutdown_information", "name TEXT, row_data TEXT, row_decoded TEXT, type TEXT"),
        ("Windows_lastupdate", "name TEXT, row_data TEXT, type TEXT"),
        ("Windows_lastupdate_subkeys", "subkey TEXT, name TEXT, row_data TEXT, row_decoded TEXT, type TEXT"),
        # 'Search_Explorer_bar' was created here and never populated. The same
        # artifact is WordWheelQuery in the live parser, which is the name the
        # industry uses and the one the GUI already knows.
    ]

    for table_name, schema in tables_basic:
        cursor.execute(f'CREATE TABLE IF NOT EXISTS {table_name} ({schema})')

    # Enhanced system info tables
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ComputerNameInfo (
        computer_name TEXT, registered_owner TEXT, registered_organization TEXT,
        product_id TEXT, installation_date TEXT, parsed_at TEXT
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS TimeZoneInfo (
        time_zone_name TEXT, standard_name TEXT, daylight_name TEXT,
        bias INTEGER, active_time_bias INTEGER, daylight_bias INTEGER,
        utc_offset TEXT, display_name TEXT, standard_name_raw TEXT,
        daylight_name_raw TEXT, standard_start_rule TEXT,
        daylight_start_rule TEXT, dynamic_dst_disabled TEXT,
        agrees_with_tzi TEXT, parsed_at TEXT
    )''')

    # One row per network, joining Signatures\Unmanaged to Profiles on
    # ProfileGuid. Built from the values already read out of the hive, which is
    # why it works here at all - the live parser used to do this join by
    # reading the Profiles key back through the registry API, so offline it
    # could never have worked.
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS NetworkProfiles (
        profile_guid TEXT, profile_name TEXT, description TEXT,
        signature TEXT, first_network TEXT, gateway_mac TEXT,
        dns_suffix TEXT, category INTEGER, category_label TEXT,
        name_type INTEGER, name_type_label TEXT, managed INTEGER,
        managed_label TEXT, source INTEGER, date_created TEXT,
        date_last_connected TEXT, key_path TEXT, last_written TEXT,
        time_basis TEXT, parsed_at TEXT
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS NetworkInterfacesInfo (
        interface_id TEXT, ip_address TEXT, subnet_mask TEXT,
        default_gateway TEXT, dhcp_enabled INTEGER, dhcp_server TEXT,
        dns_servers TEXT, mac_address TEXT, gateway_ip TEXT,
        gateway_hardware_mac TEXT, dns_suffix TEXT, lease_obtained TEXT,
        lease_expires TEXT, parsed_at TEXT
    )''')

    # An existing case database is evidence: it gets ALTER TABLE ADD COLUMN
    # and never a rebuild, so a re-parse gains the decoded columns and loses
    # nothing already in it.
    for _t, _cols in (
            ("time_zone", {"decoded": "TEXT"}),
            ("network_interfaces", {"decoded": "TEXT"}),
            ("Network_list", {"decoded": "TEXT", "parsed_at": "TEXT"}),
            ("BAM", {"decoded": "TEXT", "name_kind": "TEXT",
                     "name_kind_raw": "INTEGER", "trailing_value": "INTEGER"}),
            ("DAM", {"decoded": "TEXT", "name_kind": "TEXT",
                     "name_kind_raw": "INTEGER", "trailing_value": "INTEGER"}),
            ("TimeZoneInfo", {"daylight_bias": "INTEGER", "utc_offset": "TEXT",
                              "display_name": "TEXT",
                              "standard_name_raw": "TEXT",
                              "daylight_name_raw": "TEXT",
                              "standard_start_rule": "TEXT",
                              "daylight_start_rule": "TEXT",
                              "dynamic_dst_disabled": "TEXT",
                              "agrees_with_tzi": "TEXT"}),
            ("NetworkInterfacesInfo", {"gateway_ip": "TEXT",
                                       "gateway_hardware_mac": "TEXT",
                                       "dns_suffix": "TEXT",
                                       "lease_obtained": "TEXT",
                                       "lease_expires": "TEXT"}),
            # Which shell view wrote the bag - see _bag_view() below.
            ("Shellbags", {"node_slot": "INTEGER", "bag_views": "TEXT"}),
    ):
        try:
            _have = {r[1].lower() for r
                     in cursor.execute('PRAGMA table_info("%s")' % _t)}
        except Exception:
            continue
        for _c, _ty in _cols.items():
            if _have and _c.lower() not in _have:
                try:
                    cursor.execute('ALTER TABLE "%s" ADD COLUMN "%s" %s'
                                   % (_t, _c, _ty))
                except Exception as _exc:
                    logging.debug("could not add %s.%s: %s", _t, _c, _exc)

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS WindowsUpdateInfo (
        last_check_time TEXT, last_install_time TEXT, au_options INTEGER,
        scheduled_install_day INTEGER, scheduled_install_time INTEGER, parsed_at TEXT
    )''')

    # One row per hive the parse touched, whether or not anything was replayed.
    # A dirty hive that could not be recovered is evidence about the evidence:
    # the rows in every other table may not be the final state of that registry,
    # and that has to be recorded rather than inferred from a console message
    # nobody kept.
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS registry_hive_state (
        hive_name TEXT, hive_path TEXT, sequence_1 INTEGER, sequence_2 INTEGER,
        was_dirty INTEGER, logs_found TEXT, log_format TEXT, replayed INTEGER,
        entries_applied INTEGER, pages_applied INTEGER, highest_sequence INTEGER,
        source_sha256 TEXT, acquisition_route TEXT, reason TEXT, parsed_at TEXT
    )''')

    # Additive migration, same as key_last_write below: a case database from an
    # earlier build has this table without source_sha256, CREATE TABLE IF NOT
    # EXISTS will not add it, and the insert would then fail inside a try that
    # logs and continues - so the table would quietly stop gaining rows.
    try:
        cursor.execute("PRAGMA table_info(registry_hive_state)")
        _hs_cols = [c[1] for c in cursor.fetchall()]
        if _hs_cols and "source_sha256" not in _hs_cols:
            cursor.execute(
                "ALTER TABLE registry_hive_state ADD COLUMN source_sha256 TEXT")
        if _hs_cols and "acquisition_route" not in _hs_cols:
            cursor.execute(
                "ALTER TABLE registry_hive_state ADD COLUMN acquisition_route TEXT")
    except sqlite3.Error as _e:
        logging.debug("source_sha256 migration: %s", _e)


    # ---- what a tree walk cannot see -------------------------------------
    # Sections 13 and 14 of the registry guide. A tree walk reports what the
    # root can reach; these three come from walking the allocator instead.

    # An nk record can carry a class name, a second string separate from the
    # key's name. Most keys have none, and it is where the four keys under
    # Control\Lsa keep the machine's boot key - data in a field most registry
    # viewers do not render at all.
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS registry_class_names (
        hive_name TEXT, key_path TEXT, key_name TEXT, class_name TEXT,
        class_length INTEGER, key_last_write TEXT, parsed_at TEXT,
        UNIQUE(hive_name, key_path, class_name)
    )''')

    # Keys do not get a security descriptor each; identical ones are stored
    # once and shared, carrying a count of how many keys use them. One row per
    # distinct descriptor. A descriptor with a reference count of 1, where its
    # siblings share one, is a key whose permissions were changed - and that is
    # visible here without reading a single ACE.
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS registry_security_descriptors (
        hive_name TEXT, sk_offset INTEGER, descriptor_hash TEXT,
        reference_count INTEGER,
        owner_sid TEXT, group_sid TEXT, dacl_ace_count INTEGER,
        sacl_ace_count INTEGER, descriptor_size INTEGER, sample_key_path TEXT,
        parsed_at TEXT,
        -- Keyed on the descriptor itself rather than on where it sat: a live
        -- read has no offset, and two keys sharing a hash share permissions.
        UNIQUE(hive_name, descriptor_hash)
    )''')

    # Deleting a key does not erase it: Windows flips the cell's size from
    # negative to positive and moves on, leaving the signature, name, timestamp
    # and pointers in place until something allocates over them. "Carved", not
    # "deleted" - a key in free space was removed, which is not the same as
    # somebody having removed it deliberately.
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS registry_carved_keys (
        hive_name TEXT, cell_offset INTEGER, key_name TEXT, key_path TEXT,
        parent_resolved INTEGER, key_last_write TEXT,
        subkey_count INTEGER, value_count INTEGER, record_state TEXT,
        parsed_at TEXT,
        UNIQUE(hive_name, cell_offset)
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS registry_carved_values (
        hive_name TEXT, cell_offset INTEGER, parent_cell_offset INTEGER,
        key_path TEXT, value_name TEXT, value_type TEXT,
        data_size INTEGER, is_inline INTEGER, data TEXT, record_state TEXT,
        parsed_at TEXT,
        UNIQUE(hive_name, cell_offset)
    )''')

    # A key records when it was last written; its values record nothing at
    # all. This table is the only place that says WHICH value changed, and it
    # comes from the transaction logs rather than from the hive: the hive holds
    # the state before the pending transactions, the log holds it after, and
    # the bytes that differ name the value.
    #
    # Scope is a property of the row, not a caveat in a manual - the logs hold
    # recent transactions, not full history, so an absence here means nothing.
    # One row per key, with its last-write time. The key-level surface: here
    # the timestamp is unambiguous because the ROW IS THE KEY. On a value row
    # the same number is only ever an upper bound, which is why it is written
    # there through time_basis rather than on its own.
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
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS registry_key_times (
        hive_name TEXT, key_path TEXT, key_last_write TEXT, cell_offset INTEGER,
        parsed_at TEXT,
        UNIQUE(hive_name, key_path)
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS registry_value_changes (
        hive_name TEXT, transaction_sequence INTEGER, change_kind TEXT,
        changed_at TEXT, key_path TEXT, value_name TEXT, value_type TEXT,
        changed_before TEXT,
        changed_after TEXT, value_before TEXT, changed_bytes INTEGER,
        cell_offset INTEGER, key_last_write TEXT, parsed_at TEXT,
        UNIQUE(hive_name, transaction_sequence, key_path, value_name)
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ShutdownInfo (
        shutdown_time TEXT, shutdown_count INTEGER, shutdown_type TEXT, clean_shutdown INTEGER,
        parsed_at TEXT
    )''')

    # DAM and BAM
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS DAM (
        subkey TEXT, name TEXT, row_data TEXT, type TEXT,
        app_name TEXT, process_path TEXT, sid TEXT, last_execution TEXT,
        execution_count INTEGER, decoded TEXT, name_kind TEXT,
        name_kind_raw INTEGER, trailing_value INTEGER,
        last_written TEXT, time_basis TEXT, parsed_at TEXT
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS BAM (
        subkey TEXT, name TEXT, row_data TEXT, type TEXT,
        app_name TEXT, process_path TEXT, sid TEXT, last_execution TEXT,
        decoded TEXT, name_kind TEXT, name_kind_raw INTEGER,
        trailing_value INTEGER,
        last_written TEXT, time_basis TEXT, parsed_at TEXT
    )''')

    # User/execution tracking
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS UserAssist (
        program_path TEXT, run_count INTEGER, last_execution TEXT,
        focus_count INTEGER, focus_time INTEGER, user_sid TEXT, parsed_at TEXT
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS Shellbags (
        file_name TEXT, short_name TEXT, shell_item_type TEXT,
        mru_position TEXT, created_date TEXT, modified_date TEXT,
        accessed_date TEXT, attributes TEXT, file_size INTEGER DEFAULT 0,
        special_folder TEXT, network_share TEXT, server_name TEXT,
        share_name TEXT, drive_letter TEXT, mft_record_number INTEGER,
        registry_path TEXT, parent_path TEXT,
        last_written TEXT, time_basis TEXT,
        node_slot INTEGER, bag_views TEXT, parsed_at TEXT, user_name TEXT
    )''')

    cursor.execute('CREATE INDEX IF NOT EXISTS idx_shellbags_file_name ON Shellbags(file_name)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_shellbags_modified_date ON Shellbags(modified_date)')

    # MRU tracking
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS RunMRU (
        command TEXT, mru_position INTEGER, access_date TEXT,
        key_last_write TEXT, parsed_at TEXT, user_name TEXT
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS OpenSaveMRU (
        subkey TEXT, name TEXT, type TEXT, file_path TEXT, file_name TEXT,
        extension TEXT, drive_letter TEXT, access_date TEXT, key_last_write TEXT,
        row_data TEXT, parsed_at TEXT, user_name TEXT
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS LastSaveMRU (
        mru_number TEXT, type TEXT, application TEXT, folder_path TEXT,
        folder_name TEXT, drive_letter TEXT, access_date TEXT, key_last_write TEXT,
        row_data TEXT, parsed_at TEXT, user_name TEXT
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS RecentDocs (
        subkey TEXT, name TEXT, row_data TEXT, type TEXT, user_name TEXT,
        mru_position INTEGER, key_last_write TEXT, parsed_at TEXT
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS TypedPaths (
        name TEXT, row_data TEXT, type TEXT, user_name TEXT,
        mru_position INTEGER, key_last_write TEXT, parsed_at TEXT
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS WordWheelQuery (
        search_term TEXT, search_type TEXT, mru_position INTEGER,
        access_date TEXT, key_last_write TEXT, parsed_at TEXT, user_name TEXT
    )''')

    # Additive migration: a case database written by an earlier build has
    # these tables without key_last_write. CREATE TABLE IF NOT EXISTS is a
    # no-op there, so the column has to be added explicitly or the insert
    # below fails on a database that already exists.
    for _mru_t in ("RunMRU", "WordWheelQuery", "OpenSaveMRU", "LastSaveMRU"):
        try:
            cursor.execute("PRAGMA table_info(%s)" % _mru_t)
            _mc = [c[1] for c in cursor.fetchall()]
            if _mc and "key_last_write" not in _mc:
                cursor.execute(
                    "ALTER TABLE %s ADD COLUMN key_last_write TEXT" % _mru_t)
        except sqlite3.Error as _e:
            logging.debug("key_last_write migration for %s: %s", _mru_t, _e)

    # The subtractive counterpart, mirroring Regclaw. last_written / time_basis
    # are filled by the time-basis pass for any table that has them and a column
    # it takes for a key path - it takes the NAME "subkey" for one, and in these
    # two tables subkey is a file extension (".jpg", "exe"). The match never
    # happened, so both columns were empty on every row, and because they sat
    # mid-table a positionally-filled tab showed the parse time under
    # "Last Written". One statement per column: a (name, DDL) pair list is the
    # shape Sentinel's extract-schema.js reads as a table definition.
    for _dead_t in ("OpenSaveMRU", "RecentDocs"):
        try:
            cursor.execute("PRAGMA table_info(%s)" % _dead_t)
            _dc = [c[1] for c in cursor.fetchall()]
            if not _dc:
                continue
            if "last_written" in _dc:
                cursor.execute(
                    "ALTER TABLE %s DROP COLUMN last_written" % _dead_t)
            if "time_basis" in _dc:
                cursor.execute(
                    "ALTER TABLE %s DROP COLUMN time_basis" % _dead_t)
        except sqlite3.Error as _e:
            # Needs SQLite 3.35+. Older builds keep the columns; the tabs place
            # values by name now, so they render empty instead of shifting.
            logging.debug("dead-column drop for %s: %s", _dead_t, _e)

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS MUICache (
        app_path TEXT, app_name TEXT, company TEXT, file_extension TEXT,
        parsed_at TEXT, user_name TEXT
    )''')

    # NEW: Browser & Software Inventory Tables
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS BrowserHistory (
        browser TEXT, url TEXT, title TEXT, visit_count INTEGER,
        last_visit TEXT, parsed_at TEXT, user_name TEXT
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS InstalledSoftware (
        display_name TEXT, display_version TEXT, publisher TEXT,
        install_date TEXT, install_location TEXT, uninstall_string TEXT, parsed_at TEXT
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS SystemServices (
        service_name TEXT PRIMARY KEY, display_name TEXT, description TEXT,
        image_path TEXT, start_type INTEGER, service_type INTEGER,
        error_control INTEGER, status TEXT, parsed_at TEXT
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS AutoStartPrograms (
        location TEXT, program_name TEXT, command TEXT, key_path TEXT,
        startup_state TEXT, disabled_at TEXT, record_state TEXT,
        last_written TEXT, time_basis TEXT,
        parsed_at TEXT,
        PRIMARY KEY (location, program_name)
    )''')

    # A case database from an earlier build has this table without
    # record_state, and CREATE TABLE IF NOT EXISTS will not add it.
    try:
        cursor.execute("PRAGMA table_info(AutoStartPrograms)")
        _asp_cols = [c[1] for c in cursor.fetchall()]
        if _asp_cols and "record_state" not in _asp_cols:
            cursor.execute(
                "ALTER TABLE AutoStartPrograms ADD COLUMN record_state TEXT")
    except sqlite3.Error as _e:
        logging.debug("record_state migration: %s", _e)

    # NEW: USB Device Tables (5 tables)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS USBDevices (
        device_id TEXT PRIMARY KEY, description TEXT, manufacturer TEXT,
        friendly_name TEXT, last_connected TEXT
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS USBProperties (
        device_id TEXT, property_name TEXT, property_value TEXT,
        property_type TEXT, PRIMARY KEY (device_id, property_name)
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS USBInstances (
        device_id TEXT, instance_id TEXT, parent_id TEXT,
        service TEXT, status TEXT, PRIMARY KEY (device_id, instance_id)
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS USBStorageDevices (
        device_id TEXT PRIMARY KEY, friendly_name TEXT, serial_number TEXT,
        vendor_id TEXT, product_id TEXT, revision TEXT,
        first_connected TEXT, last_connected TEXT, last_removed TEXT,
        parsed_at TEXT
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS USBStorageVolumes (
        device_id TEXT, volume_guid TEXT, volume_name TEXT,
        drive_letter TEXT, parsed_at TEXT,
        PRIMARY KEY (device_id, volume_guid)
    )''')

    # SuspiciousIndicators and AutoStartSuspicious used to be created here.
    #
    # They existed only in the offline parser, so the same machine produced a
    # different schema depending on acquisition, and nothing in the GUI or the
    # correlation engine ever read them. Worse, they were wrong: on a reference
    # image they flagged BoxSync and GoogleDriveSync as "Potential hacking/
    # malware tool detected" and OneDriveSetup as a suspicious path.
    #
    # No evidence is lost by removing them - every row they held is already in
    # AutoStartPrograms, InstalledSoftware or SystemServices. What is removed is
    # a verdict, and a verdict belongs to a Wing, where the rule is visible and
    # can be tuned, not to a parser.

    # User Profiles
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS UserProfiles (
        user_sid TEXT PRIMARY KEY, username TEXT, profile_path TEXT,
        profile_image_path TEXT, profile_loaded INTEGER, parsed_at TEXT
    )''')

    conn.commit()
    print("[OK] All 40+ tables created successfully\n")

    # Account lookup, built before any phase that attributes a row to a user.
    # The identity phase at the end rebuilds it and writes UserAccounts; this is
    # only the SID/name table the per-hive attribution needs, and it has to exist
    # before the first phase that opens a user hive - otherwise every lookup
    # raises NameError into a surrounding try/except and the rows come out
    # unattributed with nothing reported.
    try:
        _identity_accounts, _ = user_identity.build_user_accounts(
            sam_reg_hive, Software_reg_hive, system_reg_hive)
    except Exception as e:
        logging.debug(f"identity lookup unavailable: {e}")
        _identity_accounts = []

    # ========================================================================
    # DATA COLLECTION PHASES
    # ========================================================================

    # PHASE: AutoStart Programs (Run/RunOnce)
    print("[AUTOSTART] Collecting Run/RunOnce entries...")
    run_paths = {
        "machine_run": (Software_reg_hive, "Microsoft\\Windows\\CurrentVersion\\Run"),
        "machine_run_once": (Software_reg_hive, "Microsoft\\Windows\\CurrentVersion\\RunOnce"),
    }
    
    # User run paths will be processed for each NTUSER hive
    user_run_paths = {
        "user_run": "Software\\Microsoft\\Windows\\CurrentVersion\\Run",
        "user_run_once": "Software\\Microsoft\\Windows\\CurrentVersion\\RunOnce"
    }

    for table_name, (hive, key) in run_paths.items():
        try:
            output = read_registry_values(hive, key)
            location = "HKLM" if "machine" in table_name else "HKCU"
            auto_type = "Run" if "run_once" not in table_name else "RunOnce"

            for name, (data, value_type) in output.items():
                try:
                    command_str = str(data)
                    if not check_exists(cursor, table_name, ['name'], (name,)):
                        cursor.execute(f'INSERT INTO {table_name} (name, row_data, type) VALUES (?, ?, ?)',
                                      (name, command_str, value_type))
                    
                    # Also populate AutoStartPrograms table.
                    # Space-separated, the form the other 155 locations in this
                    # table already use. "HKLM\Run" was a second spelling of the
                    # same location, so a query filtering on "HKLM Run" found
                    # the live parser's rows and silently not these.
                    full_location = f"{location} {auto_type}"
                    if not check_exists(cursor, 'AutoStartPrograms', ['location', 'program_name'], (full_location, name)):
                        cursor.execute('''INSERT INTO AutoStartPrograms
                            (location, program_name, command, key_path,
                             record_state, parsed_at)
                            VALUES (?, ?, ?, ?, ?, ?)''',
                            (full_location, name, command_str, key, LIVE_STATE,
                             get_current_forensic_timestamp()))

                    # An AutoStartSuspicious verdict was written here. Every entry it
                    # flagged is already recorded in AutoStartPrograms with its full
                    # command, so nothing observed is lost - only the guess about it.

                except Exception as e:
                    logging.error(f"Error processing autostart {name}: {e}")
        except Exception as e:
            logging.error(f"Error reading {table_name}: {e}")
    
    # Process user run paths from all NTUSER hives
    for ntuser_idx, Ntuser_reg_hive in enumerate(ntuser_hives):
        # Whose hive is this? Rows below are attributed to this user.
        _hive_user = user_identity.display_owner(Ntuser_reg_hive, _identity_accounts)
        for table_name, key in user_run_paths.items():
            try:
                output = read_registry_values(Ntuser_reg_hive, key)
                location = "HKCU"
                auto_type = "Run" if "run_once" not in table_name else "RunOnce"

                for name, (data, value_type) in output.items():
                    try:
                        command_str = str(data)
                        if not check_exists(cursor, table_name, ['name'], (name,)):
                            cursor.execute(f'INSERT INTO {table_name} (name, row_data, type) VALUES (?, ?, ?)',
                                          (name, command_str, value_type))
                        
                        # Also populate AutoStartPrograms table (same spelling
                        # rule as the machine-wide pass above).
                        full_location = f"{location} {auto_type}"
                        if not check_exists(cursor, 'AutoStartPrograms', ['location', 'program_name'], (full_location, name)):
                            cursor.execute('''INSERT INTO AutoStartPrograms
                                (location, program_name, command, key_path,
                                 record_state, parsed_at)
                                VALUES (?, ?, ?, ?, ?, ?)''',
                                (full_location, name, command_str, key,
                                 LIVE_STATE, get_current_forensic_timestamp()))

                        # An AutoStartSuspicious verdict was written here. Every entry it
                        # flagged is already recorded in AutoStartPrograms with its full
                        # command, so nothing observed is lost - only the guess about it.

                    except Exception as e:
                        logging.error(f"Error processing autostart {name}: {e}")
            except Exception as e:
                logging.debug(f"Error reading {table_name} from NTUSER[{ntuser_idx}]: {e}")

    conn.commit()
    print("[OK] AutoStart programs collected\n")

    # PHASE: DAM/BAM (already implemented, ENHANCED)
    print("[DAM/BAM] Collecting Desktop and Background Activity Moderator data...")
    try:
        # Get active ControlSet for this system
        active_controlset = get_active_controlset(system_reg_hive)
        logging.info(f"Using active ControlSet for DAM/BAM extraction: {active_controlset}")
        
        # DAM - Enhanced with full binary parsing and execution tracking
        # Try BOTH version paths: State\UserSettings (Win10 1809+) AND UserSettings (Win10 1709-1803)
        dam_paths = ["Services\\dam\\State\\UserSettings", "Services\\dam\\UserSettings"]
        dam_subkeys = {}
        
        for dam_path in dam_paths:
            # Try all ControlSet paths for each version path
            for cs_num in [int(active_controlset[-1]) if active_controlset[-1].isdigit() else 1, 1, 2, 3]:
                cs_name = f"ControlSet{cs_num:03d}"
                try:
                    full_path = f"{cs_name}\\{dam_path}"
                    logging.debug(f"Checking DAM path: {full_path}")
                    subkeys = get_subkeys(system_reg_hive, full_path)
                    if subkeys:
                        logging.debug(f"Successfully read DAM data from: {full_path}")
                        logging.debug(f"Using registry_binary_parser.parse_dam_entry() for DAM data")
                        dam_subkeys.update(subkeys)
                except Exception as e:
                    logging.debug(f"DAM path not found: {full_path}")

        for subkey, values in dam_subkeys.items():
            for name, (data, value_type) in values.items():
                try:
                    # Initialize default values
                    process_path = name
                    app_name = os.path.basename(name) if name else ''
                    last_execution = ''
                    execution_count = 0
                    
                    # Parse binary data for timestamp and path
                    if value_type == "REG_BINARY":
                        binary_data = data if isinstance(data, bytes) else data.encode('latin-1')
                        try:
                            parsed_data = registry_binary_parser.parse_dam_entry(name, binary_data)
                            app_name = parsed_data.get('app_name', '')
                            process_path = parsed_data.get('process_path', name)
                            last_execution = parsed_data.get('last_execution', '')
                        except Exception as e:
                            logging.error(f"Error parsing DAM binary data for {name}: {e}")
                            process_path = name
                            app_name = os.path.basename(process_path)
                    else:
                        process_path = name
                        app_name = os.path.basename(process_path)
                    
                    # Check for additional metadata values (similar to main RegClaw)
                    # LastAccessed: Alternative timestamp field
                    if 'LastAccessed' in values:
                        try:
                            last_accessed_data, last_accessed_type = values['LastAccessed']
                            if isinstance(last_accessed_data, int):
                                # Convert FILETIME integer to datetime using utility
                                dt = filetime_to_datetime(last_accessed_data)
                                last_execution = format_forensic_timestamp(dt)
                            elif isinstance(last_accessed_data, bytes) and len(last_accessed_data) >= 8:
                                # Parse FILETIME from bytes
                                from Artifacts_Collectors.registry_binary_parser import parse_filetime
                                last_execution = parse_filetime(last_accessed_data[:8])
                        except Exception as e:
                            logging.debug(f"Could not parse LastAccessed for {name}: {e}")
                    
                    # AccessCount: Execution count field
                    if 'AccessCount' in values:
                        try:
                            access_count_data, access_count_type = values['AccessCount']
                            if isinstance(access_count_data, int):
                                execution_count = access_count_data
                            elif isinstance(access_count_data, bytes) and len(access_count_data) >= 4:
                                execution_count = struct.unpack('<I', access_count_data[:4])[0]
                            else:
                                execution_count = int(access_count_data)
                        except Exception as e:
                            logging.debug(f"Could not parse AccessCount for {name}: {e}")
                            execution_count = 0

                    # Extract SID from subkey path
                    sid = _extract_sid_from_path(subkey)
                    
                    # Insert into database with all columns
                    if not check_exists(cursor, 'DAM', ['subkey', 'name'], (subkey, name)):
                        _dam_blob = (registry_binary_parser.parse_bam_blob(data)
                                     if isinstance(data, bytes) else {})
                        cursor.execute('''INSERT INTO DAM
                            (subkey, name, row_data, decoded, type, app_name, process_path, sid,
                             last_execution, execution_count, name_kind, name_kind_raw,
                             trailing_value, parsed_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                            (subkey, name, str(data)[:200],
                             registry_binary_parser.render_registry_value(
                                 'bam', name, data, value_type),
                             value_type, app_name, process_path, sid,
                             last_execution, execution_count,
                             _dam_blob.get('name_kind'),
                             _dam_blob.get('name_kind_raw'),
                             _dam_blob.get('trailing_value'),
                             get_current_forensic_timestamp()))
                except Exception as e:
                    logging.error(f"Error processing DAM entry {name}: {e}")

        # BAM - Try BOTH version paths: State\UserSettings (Win10 1809+) AND UserSettings (Win10 1709-1803)
        bam_paths = ["Services\\bam\\State\\UserSettings", "Services\\bam\\UserSettings"]
        bam_subkeys = {}
        
        for bam_path in bam_paths:
            # Try all ControlSet paths for each version path
            for cs_num in [int(active_controlset[-1]) if active_controlset[-1].isdigit() else 1, 1, 2, 3]:
                cs_name = f"ControlSet{cs_num:03d}"
                try:
                    full_path = f"{cs_name}\\{bam_path}"
                    logging.debug(f"Checking BAM path: {full_path}")
                    subkeys = get_subkeys(system_reg_hive, full_path)
                    if subkeys:
                        logging.debug(f"Successfully read BAM data from: {full_path}")
                        logging.debug(f"Using registry_binary_parser.parse_bam_entry() for BAM data")
                        bam_subkeys.update(subkeys)
                except Exception as e:
                    logging.debug(f"BAM path not found: {full_path}")

        for subkey, values in bam_subkeys.items():
            for name, (data, value_type) in values.items():
                try:
                    process_path = ''
                    app_name = ''
                    last_execution = ''
                    name_kind = ''
                    name_kind_raw = None
                    trailing_value = None

                    if registry_binary_parser.is_bam_metadata(name):
                        # Version and SequenceNumber are the key's own
                        # bookkeeping, not programs. Writing them as programs
                        # gave two rows per SID an app_name and a process_path
                        # of "Version" and "SequenceNumber" - paths that exist
                        # nowhere.
                        pass
                    elif value_type == "REG_BINARY":
                        binary_data = data if isinstance(data, bytes) else data.encode('latin-1')
                        try:
                            parsed_data = registry_binary_parser.parse_bam_entry(name, binary_data)
                            process_path = parsed_data.get('process_path', name)
                            # The whole 24-byte blob. The uint32 at offset 16
                            # says whether the value NAME is a device path or a
                            # package family name; only the first eight bytes
                            # were ever read.
                            blob = registry_binary_parser.parse_bam_blob(binary_data)
                            last_execution = (blob['last_execution']
                                              or parsed_data.get('last_execution', ''))
                            name_kind = blob['name_kind']
                            name_kind_raw = blob['name_kind_raw']
                            trailing_value = blob['trailing_value']
                            app_name = os.path.basename(process_path)
                        except Exception as e:
                            logging.error(f"Error parsing BAM binary data for {name}: {e}")
                            process_path = name
                            app_name = os.path.basename(name) if name else ''
                    else:
                        process_path = name
                        app_name = os.path.basename(name) if name else ''

                    decoded = registry_binary_parser.render_registry_value(
                        'bam', name, data, value_type)

                    # Extract SID from subkey path
                    sid = _extract_sid_from_path(subkey)
                    
                    # Insert into database
                    if not check_exists(cursor, 'BAM', ['subkey', 'name'], (subkey, name)):
                        # execution_flags is gone from both parsers. It read a
                        # value named 'Flags' that these keys do not have, so it
                        # was 0 on every row - a constant presented as a finding.
                        cursor.execute('''INSERT INTO BAM
                            (subkey, name, row_data, decoded, type, app_name, process_path, sid,
                             last_execution, name_kind, name_kind_raw, trailing_value, parsed_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                            (subkey, name, str(data)[:200], decoded, value_type,
                             app_name or None, process_path or None, sid,
                             last_execution, name_kind, name_kind_raw,
                             trailing_value, get_current_forensic_timestamp()))
                except Exception as e:
                    logging.error(f"Error processing BAM entry {name}: {e}")

        conn.commit()
        print("[OK] DAM/BAM data collected\n")
    except Exception as e:
        logging.error(f"Error with DAM/BAM: {e}")

    # PHASE: UserAssist
    print("[USERASSIST] Collecting program execution tracking...")
    try:
        userassist_base_path = "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\UserAssist"
        
        # Process each NTUSER hive file
        for ntuser_idx, Ntuser_reg_hive in enumerate(ntuser_hives):
            # Whose hive is this? Rows below are attributed to this user.
            _hive_user = user_identity.display_owner(Ntuser_reg_hive, _identity_accounts)
            hive_label = f"NTUSER[{ntuser_idx}]" if len(ntuser_hives) > 1 else "NTUSER"
            print(f"  Processing {hive_label}: {os.path.basename(Ntuser_reg_hive)}")

            # Whose hive is this? The live parser records the account SID here;
            # offline used to store the UserAssist GUID instead, which names a
            # counter set rather than a person and made the two disagree.
            # Resolve to a SID so this column holds the same kind of value as
            # the live parser writes; the identity pass then renders both as
            # "SID (MACHINE\\username)". Falls back to the name when the SID
            # cannot be resolved - still a person, never a counter-set GUID.
            _ua_user = (user_identity.resolve_hive_owner_sid(
                            Ntuser_reg_hive, _identity_accounts)
                        or user_identity.identify_ntuser_hive(Ntuser_reg_hive))

            try:
                reg = Registry.Registry(Ntuser_reg_hive)
                userassist_key = reg.open(userassist_base_path)

                for guid_subkey in userassist_key.subkeys():
                    guid_name = guid_subkey.name()
                    count_path = f"{userassist_base_path}\\{guid_name}\\Count"

                    try:
                        count_values = read_registry_values(Ntuser_reg_hive, count_path)

                        for value_name, (data, value_type) in count_values.items():
                            try:
                                if value_type != "REG_BINARY":
                                    continue

                                binary_data = data if isinstance(data, bytes) else data.encode('latin-1')
                                parsed_data = registry_binary_parser.parse_userassist_entry(value_name, binary_data)

                                program_path = parsed_data.get('program_path', '')
                                run_count = parsed_data.get('run_count', 0)
                                last_execution = parsed_data.get('last_execution', '')
                                focus_count = parsed_data.get('focus_count', 0)
                                focus_time_ms = parsed_data.get('focus_time', 0)
                                
                                # Attribute to the hive's owner. Falls back to the
                                # hive label rather than the GUID when the owner
                                # cannot be determined - never a misleading name.
                                _owner = _ua_user or hive_label
                                if not user_identity.row_exists_for_sid(
                                        cursor, 'UserAssist', ['program_path'],
                                        (program_path,), 'user_sid', _owner):
                                    cursor.execute('''INSERT INTO UserAssist
                                        (program_path, run_count, last_execution, focus_count, focus_time, user_sid, parsed_at)
                                        VALUES (?, ?, ?, ?, ?, ?, ?)''',
                                        (program_path, run_count, last_execution, focus_count,
                                         int(focus_time_ms), _owner, get_current_forensic_timestamp()))
                            except Exception as e:
                                logging.debug(f"Error parsing UserAssist entry: {e}")

                    except Exception as e:
                        logging.error(f"Error accessing UserAssist Count: {e}")

            except Exception as e:
                logging.error(f"Error accessing UserAssist in {hive_label}: {e}")

        conn.commit()
        print("[OK] UserAssist data collected\n")
    except Exception as e:
        logging.error(f"Error with UserAssist: {e}")

    # Helper for RecentDocs subkey processing
    def process_recent_docs_key(hive, path, subkey_label, cursor):
        # Attribute to the hive handed in, not to a closure variable.
        _hive_user = user_identity.display_owner(hive, _identity_accounts)
        try:
            values = read_registry_values(hive, path)

            # MRUListEx is the access order, not evidence in itself - it is not
            # stored as a row, but it is the only record of WHICH document was
            # opened most recently, so decode it rather than discarding it.
            mru_order = []
            for _n, (_d, _t) in values.items():
                if _n.lower() == 'mrulistex' and isinstance(_d, bytes):
                    try:
                        mru_order = registry_binary_parser.parse_mru_list_ex(_d)
                    except Exception as e:
                        logging.debug(f"MRUListEx unreadable in {subkey_label}: {e}")
                    break

            _lastwrite = key_last_write(hive, path)
            _stamp = get_current_forensic_timestamp()

            for name, (data, value_type) in values.items():
                if name.lower() == 'mrulistex': continue
                try:
                    if value_type == 'REG_BINARY' and isinstance(data, bytes):
                        try:
                            parsed_filename = registry_binary_parser.parse_recentdocs_entry(data)
                            if not parsed_filename: parsed_filename = str(data)[:200]
                        except: parsed_filename = str(data)[:200]
                    else: parsed_filename = str(data)[:200]

                    # Position in the MRU list; 0 is the most recent. -1 means the
                    # entry is not listed, which is itself worth seeing.
                    mru_position = -1
                    try:
                        _idx = int(name)
                        if mru_order and _idx in mru_order:
                            mru_position = mru_order.index(_idx)
                    except (ValueError, TypeError):
                        pass

                    if not check_exists(cursor, 'RecentDocs', ['name', 'subkey', 'row_data', 'user_name'], (name, subkey_label, parsed_filename, _hive_user)):
                        cursor.execute('INSERT INTO RecentDocs (subkey, name, row_data, type, user_name, mru_position, key_last_write, parsed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                                      (subkey_label, name, str(parsed_filename), value_type, _hive_user,
                                       mru_position, _lastwrite, _stamp))
                except Exception as e:
                    logging.debug(f"Error with RecentDocs entry in {subkey_label}: {e}")
        except Exception as e:
            logging.debug(f"Error accessing RecentDocs path {path}: {e}")

    # The evidence machine's UTC offset, read BEFORE any shell item is
    # decoded. Shell items carry DOS date/time, which is that machine's local
    # wall clock with no zone in it, so the decoder needs the offset to return
    # a real UTC moment rather than relabelling a local one.
    #
    # Read here rather than where TimeZoneInfo is written, which happens more
    # than a thousand lines later - setting it there applied it to nothing
    # while looking perfectly correct.
    try:
        # Through the parser's own ControlSet-resolving reader. An offline
        # SYSTEM hive has no CurrentControlSet - that key is assembled at boot
        # and never stored - so the live path finds nothing here and reports no
        # error, which is exactly what the first version of this did.
        _tz_values, _ = read_registry_multi_path(
            system_reg_hive, "Control" + chr(92) + "TimeZoneInformation",
            controlset_dependent=True, active_controlset=active_controlset)
        _raw_bias = 0
        for _n, _v in (_tz_values or {}).items():
            if str(_n).lower() == "bias":
                _raw_bias = _v[0] if isinstance(_v, (tuple, list)) else _v
                break
        _bias_minutes = registry_binary_parser.set_evidence_bias(_raw_bias)
        if _bias_minutes:
            print("[OK] Evidence timezone offset UTC%s - shell item times "
                  "converted from the evidence machine's local clock"
                  % registry_binary_parser.utc_offset_label(_bias_minutes))
        else:
            print("[--] No timezone bias in this evidence - shell item times "
                  "stay on the evidence machine's local clock")
    except Exception as _exc:
        logging.debug("evidence bias: %s", _exc)

    # PHASE: Shellbags
    print("[SHELLBAGS] Collecting folder access history...")
    
    # Explorer files a window's view settings under Shell; a common File
    # Open/Save dialog files its own under ComDlg. Listed in that order rather
    # than alphabetically, and fixed rather than arbitrary so a re-parse is
    # stable.
    _VIEW_ORDER = {"Shell": 0, "ComDlg": 1}

    def _bag_view(reg, bags_path, folder_key):
        """Which kind of shell view wrote this folder's bag, if any.

        A BagMRU key carries a NodeSlot DWORD naming a subkey of the Bags tree
        beside it, and that subkey holds the view settings. It is the only
        place in the hive that distinguishes a bag written by an Explorer
        window from one written by a file dialog inside another program.

        The slot is read from the folder's OWN key. An item is value N of key
        P and the folder it names is P then N, so reading the slot off P would
        give every row its parent's view - wrong, and entirely plausible.

        Returns (node_slot, views); either may be None. The reference system
        has 58 of 839 keys with no NodeSlot at all, and an empty column is the
        honest answer for those.
        """
        try:
            key = reg.open(folder_key)
            slot = key.value("NodeSlot").value()
        except Exception:
            return None, None
        if not isinstance(slot, int):
            return None, None
        try:
            bag = reg.open(bags_path + chr(92) + str(slot))
            views = [sub.name() for sub in bag.subkeys()]
        except Exception:
            return slot, None
        views.sort(key=lambda v: (_VIEW_ORDER.get(v, 2), v))
        return slot, (",".join(views) or None)

    def process_shellbag_subkey_recursive(reg_hive, base_path, subkey_path, cursor,
                                          parent_readable=""):
    
        _sb_user = user_identity.display_owner(reg_hive, _identity_accounts)
        """
        Recursively process Shellbags subkeys to handle nested folder structures.
        
        Args:
            reg_hive: Registry hive object
            base_path: Base registry path (e.g., "Software\\Microsoft\\Windows\\Shell\\BagMRU")
            subkey_path: Current subkey path relative to base (e.g., "0\\1\\2")
            cursor: Database cursor
        """
        try:
            full_path = f"{base_path}\\{subkey_path}" if subkey_path else base_path
            reg = Registry.Registry(reg_hive)
            current_key = reg.open(full_path)
            # The Bags tree is the sibling of BagMRU, per hive - NTUSER's Shell
            # and ShellNoRoam trees and the UsrClass tree each have their own.
            # Derived from the base path so all of them resolve without a
            # constant, and without depending on which hive this is.
            bags_path = base_path.rsplit(chr(92), 1)[0] + chr(92) + "Bags"
            
            # Collect all values from this subkey
            subkey_values = {}
            for value in current_key.values():
                name = value.name()
                # value_type() reads the type field and never raises; only
                # value() does. The consumer below compares this against
                # Registry.RegBin, so it stays the real numeric type.
                data, _typed = _value_bytes(value)
                value_type = value.value_type()
                subkey_values[name] = (data, value_type)
            
            # Parse MRU order
            mru_order = []
            if 'MRUListEx' in subkey_values:
                mrulistex_data = subkey_values['MRUListEx'][0]
                if isinstance(mrulistex_data, bytes):
                    try:
                        mru_order = registry_binary_parser.parse_mru_list_ex(mrulistex_data)
                    except Exception as e:
                        logging.error(f"Error parsing MRUListEx at {full_path}: {e}")
            
            # Process binary Shell Items
            for name, (data, val_type) in subkey_values.items():
                if name.lower() == 'mrulistex' or val_type != Registry.RegBin:
                    continue
                
                try:
                    if isinstance(data, bytes):
                        parsed_data = registry_binary_parser.parse_shellbag_entry(data)
                        
                        file_name = parsed_data.get('file_name', '')
                        if not file_name:
                            continue
                        
                        # Extract all 17 fields from parsed data
                        short_name = parsed_data.get('short_name', '')
                        shell_item_type = parsed_data.get('shell_item_type', '')
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
                        
                        # Determine MRU position
                        mru_position = ''
                        try:
                            entry_index = int(name)
                            if mru_order and entry_index in mru_order:
                                mru_position = str(mru_order.index(entry_index))
                        except (ValueError, TypeError):
                            pass
                        
                        # UsrClass.dat's root IS HKCU\Software\Classes, so a
                        # path read out of the hive starts at "Local Settings"
                        # while the live parser, reading through HKCU, records
                        # "Software\Classes\Local Settings\...". Same key, two
                        # renderings - and an analyst comparing a live case
                        # against an image saw paths that did not match. Record
                        # the full HKCU form, which is also what regedit shows.
                        registry_path = full_path
                        _sb_pfx = "Software" + chr(92) + "Classes"
                        if not registry_path.lower().startswith(_sb_pfx.lower()):
                            registry_path = (_sb_pfx + chr(92)
                                             + registry_path.lstrip(chr(92)))

                        node_slot, bag_views = _bag_view(
                            reg, bags_path, full_path + chr(92) + name)

                        if not check_exists(cursor, 'Shellbags', ['file_name', 'registry_path', 'user_name'],
                                           (file_name, registry_path, _sb_user)):
                            cursor.execute('''INSERT INTO Shellbags
                                (file_name, short_name, shell_item_type, mru_position,
                                 created_date, modified_date, accessed_date, attributes,
                                 file_size, special_folder, network_share, server_name,
                                 share_name, drive_letter, mft_record_number,
                                 registry_path, parent_path, node_slot, bag_views,
                                 parsed_at, user_name)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                                (file_name, short_name, shell_item_type, mru_position,
                                 created_date, modified_date, accessed_date, attributes,
                                 file_size, special_folder, network_share, server_name,
                                 share_name, drive_letter, mft_record_number,
                                 registry_path, parent_readable, node_slot, bag_views,
                                 get_current_forensic_timestamp(), _sb_user))
                        else:
                            # The row is already evidence and is left alone, but
                            # a column added after the case was made is empty on
                            # it. Filled in only where it is still NULL, so this
                            # adds information and overwrites nothing.
                            cursor.execute(
                                "UPDATE Shellbags SET node_slot = ?, "
                                "bag_views = ? WHERE file_name IS ? AND "
                                "registry_path IS ? AND user_name IS ? "
                                "AND node_slot IS NULL",
                                (node_slot, bag_views, file_name,
                                 registry_path, _sb_user))
                except Exception as e:
                    logging.error(f"Error parsing Shellbag entry at {full_path}\\{name}: {e}")

            # Recursively process nested subkeys.
            #
            # BagMRU nests by index - subkey N holds the children of value N in
            # this same key - so the readable folder path is accumulated on the
            # way down. registry_path only ever records the numeric chain, which
            # is why parent_path cannot be derived afterwards.
            for subkey in current_key.subkeys():
                nested_path = f"{subkey_path}\\{subkey.name()}" if subkey_path else subkey.name()
                _own = ''
                _v = subkey_values.get(subkey.name())
                if _v and isinstance(_v[0], bytes):
                    try:
                        _own = registry_binary_parser.parse_shellbag_entry(
                            _v[0]).get('file_name', '') or ''
                    except Exception:
                        _own = ''
                child_readable = (f"{parent_readable}\\{_own}"
                                  if parent_readable and _own
                                  else (_own or parent_readable))
                process_shellbag_subkey_recursive(reg_hive, base_path, nested_path,
                                                  cursor, child_readable)
                
        except Exception as e:
            logging.debug(f"Error processing Shellbag subkey {full_path}: {e}")
    
    try:
        # Define ShellBags paths for different hive types
        # 
        # IMPORTANT: Path differences between NTUSER.DAT and UsrClass.dat
        # ================================================================
        # In NTUSER.DAT: ShellBags are stored under "Software\..." paths
        # In UsrClass.dat: ShellBags are stored under "Local Settings\..." paths (NO "Software\Classes\" prefix)
        # 
        # When viewing live registry (HKEY_CURRENT_USER), Windows merges both hives:
        # - NTUSER.DAT is loaded at HKEY_USERS\{SID}
        # - UsrClass.dat is loaded at HKEY_USERS\{SID}_Classes
        # - The merged view shows UsrClass.dat paths as "Software\Classes\Local Settings\..."
        # 
        # However, when parsing hive files directly (offline analysis):
        # - NTUSER.DAT paths remain: "Software\Microsoft\Windows\Shell\BagMRU"
        # - UsrClass.dat paths are: "Local Settings\Software\Microsoft\Windows\Shell\BagMRU"
        #   (NOT "Software\Classes\Local Settings\..." - that's only in the merged view)
        #
        ntuser_shellbags_paths = [
            "Software\\Microsoft\\Windows\\Shell\\BagMRU",
            "Software\\Microsoft\\Windows\\ShellNoRoam\\BagMRU",
            "Software\\Classes\\Local Settings\\Software\\Microsoft\\Windows\\Shell\\BagMRU"
        ]
        
        # UsrClass.dat uses different base path (no "Software\Classes\" prefix)
        usrclass_shellbags_paths = [
            "Local Settings\\Software\\Microsoft\\Windows\\Shell\\BagMRU"
        ]

        # Process each NTUSER hive file
        for ntuser_idx, Ntuser_reg_hive in enumerate(ntuser_hives):
            # Whose hive is this? Rows below are attributed to this user.
            _hive_user = user_identity.display_owner(Ntuser_reg_hive, _identity_accounts)
            hive_label = f"NTUSER[{ntuser_idx}]" if len(ntuser_hives) > 1 else "NTUSER"
            print(f"  Processing {hive_label}: {os.path.basename(Ntuser_reg_hive)}")
            
            for shellbags_base_path in ntuser_shellbags_paths:
                try:
                    # Start recursive processing from the base path
                    process_shellbag_subkey_recursive(Ntuser_reg_hive, shellbags_base_path, "", cursor)
                except Exception as e:
                    logging.debug(f"Shellbags path unavailable in {hive_label}: {shellbags_base_path}")
        
        # Process each UsrClass.dat hive file (NEW)
        usrclass_hives = detected_hives.get('usrclass', [])
        if not isinstance(usrclass_hives, list):
            usrclass_hives = [usrclass_hives] if usrclass_hives else []
        
        if usrclass_hives:
            for usrclass_idx, usrclass_hive in enumerate(usrclass_hives):
                # UsrClass names its own SID in its root key.
                _uc_sid = user_identity.display_owner(usrclass_hive, _identity_accounts)
                hive_label = f"USRCLASS[{usrclass_idx}]" if len(usrclass_hives) > 1 else "USRCLASS"
                print(f"  Processing {hive_label}: {os.path.basename(usrclass_hive)}")
                
                for shellbags_base_path in usrclass_shellbags_paths:
                    try:
                        # Start recursive processing from the base path
                        process_shellbag_subkey_recursive(usrclass_hive, shellbags_base_path, "", cursor)
                    except Exception as e:
                        logging.debug(f"Shellbags path unavailable in {hive_label}: {shellbags_base_path}")
        else:
            logging.warning("No UsrClass.dat hives detected - ShellBags data will be incomplete")
            print("  [WARNING] No UsrClass.dat files found - Windows Explorer ShellBags unavailable")

        conn.commit()
        print("[OK] Shellbags data collected\n")
    except Exception as e:
        logging.error(f"Error with Shellbags: {e}")

    # PHASE: OpenSaveMRU & LastSaveMRU
    print("[MRU] Collecting Open/Save dialog history...")
    try:
        # OpenSaveMRU (ComDlg32)
        for ntuser_idx, Ntuser_reg_hive in enumerate(ntuser_hives):
            # Whose hive is this? Rows below are attributed to this user.
            _hive_user = user_identity.display_owner(Ntuser_reg_hive, _identity_accounts)
            hive_label = f"NTUSER[{ntuser_idx}]" if len(ntuser_hives) > 1 else "NTUSER"
            try:
                opensave_path = "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\ComDlg32\\OpenSavePidlMRU"
                opensave_subkeys = get_subkeys(Ntuser_reg_hive, opensave_path)
                for ext_subkey, values in opensave_subkeys.items():
                    # The key's own last-write, recorded against the key rather
                    # than inferred onto whichever entry is at MRU position 0 -
                    # the convention RunMRU and WordWheelQuery already follow.
                    _osm_kw = key_last_write(Ntuser_reg_hive,
                                             opensave_path + "\\" + ext_subkey)
                    for name, (data, value_type) in values.items():
                        if name.lower() == 'mrulistex' or value_type != "REG_BINARY":
                            continue
                        try:
                            if isinstance(data, bytes):
                                parsed_data = registry_binary_parser.parse_opensavemru_entry(data)
                                file_name = parsed_data.get('file_name', '')
                                # The subkey names the dialog's file-type filter,
                                # which is usually the extension - but under "*",
                                # the All Files filter, it is not. Copying the
                                # subkey put a literal "*" in the extension column
                                # for 18 files that really were .png, .pdf, .svg
                                # and so on, all of which the shell item names.
                                _ext = parsed_data.get('extension') or ext_subkey
                                if not check_exists(cursor, 'OpenSaveMRU', ['subkey', 'name', 'file_name', 'user_name'], (ext_subkey, name, file_name, _hive_user)):
                                    # row_data is the whole shell item blob. It
                                    # used to be cut to 100 characters of its
                                    # repr, so every one of 246 rows held a
                                    # fragment while the live parser stored all
                                    # 1167 - and nothing anywhere said so.
                                    cursor.execute('''INSERT INTO OpenSaveMRU
                                        (subkey, name, type, file_path, file_name, extension, drive_letter, access_date, key_last_write, row_data, parsed_at, user_name)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                                        (ext_subkey, name, value_type, parsed_data.get('file_path', ''), file_name, _ext,
                                         parsed_data.get('drive_letter', ''), parsed_data.get('access_date', ''),
                                         _osm_kw, str(data), get_current_forensic_timestamp(), _hive_user))
                        except Exception as e:
                            logging.debug(f"Error parsing OpenSaveMRU in {ext_subkey}: {e}")
            except Exception as e:
                logging.debug(f"Error reading OpenSaveMRU from {hive_label}: {e}")

        # LastSaveMRU
        for ntuser_idx, Ntuser_reg_hive in enumerate(ntuser_hives):
            # Whose hive is this? Rows below are attributed to this user.
            _hive_user = user_identity.display_owner(Ntuser_reg_hive, _identity_accounts)
            hive_label = f"NTUSER[{ntuser_idx}]" if len(ntuser_hives) > 1 else "NTUSER"
            try:
                lastsave_path = "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\ComDlg32\\LastVisitedPidlMRU"
                lastsave_values = read_registry_values(Ntuser_reg_hive, lastsave_path)
                _lsm_kw = key_last_write(Ntuser_reg_hive, lastsave_path)
                for name, (data, value_type) in lastsave_values.items():
                    if name.lower() == 'mrulistex' or value_type != "REG_BINARY":
                        continue
                    try:
                        if isinstance(data, bytes):
                            parsed_data = registry_binary_parser.parse_lastsavemru_entry(data)
                            app = parsed_data.get('application', '')
                            if not check_exists(cursor, 'LastSaveMRU', ['mru_number', 'application', 'user_name'], (name, app, _hive_user)):
                                cursor.execute('''INSERT INTO LastSaveMRU
                                    (mru_number, type, application, folder_path, folder_name, drive_letter, access_date, key_last_write, row_data, parsed_at, user_name)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                                    (name, value_type, app, parsed_data.get('folder_path', ''), parsed_data.get('file_name', ''),
                                     parsed_data.get('drive_letter', ''), '', _lsm_kw, str(data),
                                     get_current_forensic_timestamp(), _hive_user))
                    except Exception as e:
                        logging.debug(f"Error parsing LastSaveMRU in {hive_label}: {e}")
            except Exception as e:
                logging.debug(f"Error reading LastSaveMRU from {hive_label}: {e}")

        conn.commit()
    except Exception as e:
        logging.error(f"Error with MRU: {e}")

    # PHASE: Additional MRU types (RunMRU, WordWheelQuery)
    print("[RUNMRU/WHEELQUERY] Collecting additional history...")
    try:
        # RunMRU
        for ntuser_idx, Ntuser_reg_hive in enumerate(ntuser_hives):
            # Whose hive is this? Rows below are attributed to this user.
            _hive_user = user_identity.display_owner(Ntuser_reg_hive, _identity_accounts)
            try:
                runmru_path = "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\RunMRU"
                runmru_values = read_registry_values(Ntuser_reg_hive, runmru_path)
                # The only timestamp an MRU key has. Recorded against the key,
                # not inferred onto one entry - matching the live parser.
                _rm_kw = key_last_write(Ntuser_reg_hive, runmru_path)
                mru_list_data = runmru_values.get('MRUList', ('', ''))[0]
                mru_list = str(mru_list_data).strip()

                for value_name, (data, value_type) in runmru_values.items():
                    if value_name.lower() == 'mrulist' or value_type != "REG_SZ": continue
                    try:
                        cmd = str(data).strip()
                        if cmd:
                            parsed = registry_binary_parser.parse_runmru_entry(value_name, cmd, mru_list)
                            # Keyed by user: two accounts can type the same
                            # command, and both are evidence. On 'command' alone
                            # only the first hive's row survived, unattributed.
                            if not check_exists(cursor, 'RunMRU', ['command', 'user_name'],
                                                (parsed.get('command', cmd), _hive_user)):
                                cursor.execute('INSERT INTO RunMRU (command, mru_position, access_date, key_last_write, parsed_at, user_name) VALUES (?, ?, ?, ?, ?, ?)',
                                              (parsed.get('command', cmd), parsed.get('mru_position', -1), None, _rm_kw, get_current_forensic_timestamp(), _hive_user))
                    except Exception as e:
                        logging.debug(f"RunMRU {_hive_user}/{value_name}: {e}")
            except Exception as e:
                logging.debug(f"RunMRU hive {Ntuser_reg_hive}: {e}")

        # WordWheelQuery
        for ntuser_idx, Ntuser_reg_hive in enumerate(ntuser_hives):
            # Whose hive is this? Rows below are attributed to this user.
            _hive_user = user_identity.display_owner(Ntuser_reg_hive, _identity_accounts)
            try:
                wwq_path = "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\WordWheelQuery"
                wwq_values = read_registry_values(Ntuser_reg_hive, wwq_path)
                # The only timestamp an MRU key has. Recorded against the key,
                # not inferred onto one entry - matching the live parser.
                _ww_kw = key_last_write(Ntuser_reg_hive, wwq_path)
                mru_ex = wwq_values.get('MRUListEx', (None, None))[0]
                for v_name, (v_data, v_type) in wwq_values.items():
                    if v_name == 'MRUListEx' or v_type != "REG_BINARY": continue
                    try:
                        bin_data = v_data if isinstance(v_data, bytes) else str(v_data).encode('latin-1')
                        parsed = registry_binary_parser.parse_wordwheelquery_entry(v_name, bin_data, mru_ex)
                        term = parsed.get('search_term', '')
                        if term and not check_exists(cursor, 'WordWheelQuery',
                                                     ['search_term', 'user_name'],
                                                     (term, _hive_user)):
                            cursor.execute('INSERT INTO WordWheelQuery (search_term, search_type, mru_position, access_date, key_last_write, parsed_at, user_name) VALUES (?, ?, ?, ?, ?, ?, ?)',
                                          (term, parsed.get('search_type', 'General'),
                                           # parse_wordwheelquery_entry already
                                           # derives the position from MRUListEx.
                                           # Hardcoding -1 threw that away, so the
                                           # search-recency order - the only
                                           # ordering this artifact carries - was
                                           # absent offline and present live.
                                           parsed.get('mru_position', -1),
                                           None, _ww_kw,
                                           get_current_forensic_timestamp(), _hive_user))
                    except Exception as e:
                        logging.debug(f"WordWheelQuery {_hive_user}/{v_name}: {e}")
            except Exception as e:
                logging.debug(f"WordWheelQuery hive {Ntuser_reg_hive}: {e}")

        # MUICache
        muicache_hives = ntuser_hives + usrclass_hives
        for h_path in muicache_hives:
            # Recomputed per hive. This loop used to inherit _hive_user from the
            # WordWheelQuery loop above, so every MUICache row was credited to
            # whichever hive that loop happened to finish on.
            _mui_user = user_identity.display_owner(h_path, _identity_accounts)
            try:
                muicache_paths = ["Software\\Classes\\Local Settings\\Software\\Microsoft\\Windows\\Shell\\MuiCache",
                                 "Local Settings\\Software\\Microsoft\\Windows\\Shell\\MuiCache",
                                 "Software\\Microsoft\\Windows\\ShellNoRoam\\MUICache"]
                # One row per executable, not one per property - see the live
                # parser for the same pivot.
                apps = {}
                for m_path in muicache_paths:
                    m_values = read_registry_values(h_path, m_path)
                    for v_name, (v_data, v_type) in m_values.items():
                        if v_type != "REG_SZ": continue
                        try:
                            display_name = str(v_data).strip()
                            if not v_name or not display_name:
                                continue
                            parsed = registry_binary_parser.parse_muicache_entry(v_name, display_name)
                            path = parsed.get('app_path', '')
                            if not path:
                                continue
                            prop = (parsed.get('muicache_property') or '').lower()
                            entry = apps.setdefault(
                                path, {'file_extension': parsed.get('file_extension', ''),
                                       'app_name': '', 'company': ''})
                            if prop == 'applicationcompany':
                                entry['company'] = display_name
                            elif prop in ('friendlyappname', 'applicationname'):
                                entry['app_name'] = display_name
                            elif not entry['app_name'] and not prop:
                                entry['app_name'] = display_name
                        except Exception as e:
                            logging.debug(f"MUICache {_mui_user}/{v_name}: {e}")
                for path, entry in apps.items():
                    if not check_exists(cursor, 'MUICache', ['app_path', 'user_name'], (path, _mui_user)):
                        cursor.execute('INSERT INTO MUICache (app_path, app_name, company, file_extension, parsed_at, user_name) VALUES (?, ?, ?, ?, ?, ?)',
                                      (path, entry['app_name'], entry['company'],
                                       entry['file_extension'], get_current_forensic_timestamp(), _mui_user))
            except Exception as e:
                logging.debug(f"MUICache hive {h_path}: {e}")

        conn.commit()
        print("[OK] RunMRU/WordWheel/MUICache collected\n")
    except Exception as e:
        logging.error(f"Error with additional MRU: {e}")

    # PHASE: RecentDocs & TypedPaths
    print("[DOCUMENTS] Collecting recent documents and typed paths...")
    try:
        # RecentDocs
        for ntuser_idx, Ntuser_reg_hive in enumerate(ntuser_hives):
            # Whose hive is this? Rows below are attributed to this user.
            _hive_user = user_identity.display_owner(Ntuser_reg_hive, _identity_accounts)
            try:
                rd_path = "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\RecentDocs"
                process_recent_docs_key(Ntuser_reg_hive, rd_path, 'main', cursor)
                subkeys = get_subkeys(Ntuser_reg_hive, rd_path)
                for ext in subkeys.keys():
                    process_recent_docs_key(Ntuser_reg_hive, f"{rd_path}\\{ext}", ext, cursor)
            except: pass

        # TypedPaths
        for ntuser_idx, Ntuser_reg_hive in enumerate(ntuser_hives):
            # Whose hive is this? Rows below are attributed to this user.
            _hive_user = user_identity.display_owner(Ntuser_reg_hive, _identity_accounts)
            try:
                tp_path = "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\TypedPaths"
                tp_values = read_registry_values(Ntuser_reg_hive, tp_path)
                # TypedPaths has no MRUListEx - the order is in the value name,
                # url1 being the most recent. Normalise it to the same 0-based
                # position every other MRU table uses.
                _tp_lastwrite = key_last_write(Ntuser_reg_hive, tp_path)
                _tp_stamp = get_current_forensic_timestamp()
                for v_name, (v_data, v_type) in tp_values.items():
                    p_data = str(v_data).strip()
                    mru_position = -1
                    if v_name[:3].lower() == 'url' and v_name[3:].isdigit():
                        mru_position = int(v_name[3:]) - 1
                    if p_data and not check_exists(cursor, 'TypedPaths',
                                                   ['name', 'row_data', 'user_name'],
                                                   (v_name, p_data, _hive_user)):
                        cursor.execute('INSERT INTO TypedPaths (name, row_data, type, user_name, mru_position, key_last_write, parsed_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                                      (v_name, p_data, v_type, _hive_user,
                                       mru_position, _tp_lastwrite, _tp_stamp))
            except: pass

        conn.commit()
        print("[OK] Recent documents and typed paths collected\n")
    except Exception as e:
        logging.error(f"Error with documents: {e}")

    # PHASE: PHASE 2-4: USB DEVICE TRACKING (ENHANCED)
    print("[USB] Collecting USB device timeline...")
    try:
        # Get active ControlSet for this system
        active_controlset = get_active_controlset(system_reg_hive)
        logging.info(f"Using active ControlSet for USB extraction: {active_controlset}")
        
        # Helper function to extract VID and PID from device ID
        def extract_vid_pid(device_id):
            """Extract Vendor ID and Product ID from device ID string."""
            vid = ""
            pid = ""
            try:
                # Format: VID_XXXX&PID_XXXX or VID_XXXX&PID_XXXX&...
                parts = device_id.split('&')
                for part in parts:
                    if part.startswith('VID_'):
                        vid = part[4:]
                    elif part.startswith('PID_'):
                        pid = part[4:]
            except Exception:
                pass
            return vid, pid
        
        # 1. General USB devices (USBDevices table)
        # Use multi-path reader with ControlSet resolution
        usb_path = "Enum\\USB"
        usb_devices = {}
        
        # Try all ControlSet paths and merge results
        for cs_num in [int(active_controlset[-1]) if active_controlset[-1].isdigit() else 1, 1, 2, 3]:
            cs_name = f"ControlSet{cs_num:03d}"
            try:
                full_path = f"{cs_name}\\{usb_path}"
                logging.debug(f"Checking USB path: {full_path}")
                devices = get_subkeys(system_reg_hive, full_path)
                if devices:
                    logging.debug(f"Successfully read USB devices from: {full_path}")
                    usb_devices.update(devices)
            except Exception as e:
                logging.debug(f"USB path not found: {full_path}")

        # Under Enum\USB the first level is the device model (VID_xxxx&PID_yyyy)
        # and the level below it is one key per physical unit that was plugged
        # in. Reading only the model level recorded 19 rows where the live parser
        # recorded 21, and lost the distinction between two different sticks of
        # the same model - which is most of what USB history is asked. Descend to
        # the instance and key the row as the live parser does: <device>\<instance>.
        #
        # The value is DeviceDesc, not Description. Asking for the wrong name
        # returned nothing and raised nothing, so the column was empty on every row.
        _usb_cs = list(dict.fromkeys([active_controlset, 'ControlSet001',
                                      'ControlSet002', 'ControlSet003']))
        for device_id, values in usb_devices.items():
            try:
                instances = {}
                for _cs in _usb_cs:
                    try:
                        _got = get_subkeys(system_reg_hive,
                                           f"{_cs}\\{usb_path}\\{device_id}")
                    except Exception:
                        _got = {}
                    if _got:
                        instances.update(_got)
                if not instances:
                    # A model key with no instance below it still happens, and
                    # dropping it silently would lose the device entirely.
                    instances = {'': values}

                for instance_id, ivals in instances.items():
                    description = ivals['DeviceDesc'][0] if 'DeviceDesc' in ivals else ''
                    manufacturer = ivals['Mfg'][0] if 'Mfg' in ivals else ''
                    friendly_name = ivals['FriendlyName'][0] if 'FriendlyName' in ivals else ''

                    # Extract VID and PID from device ID
                    vid, pid = extract_vid_pid(device_id)

                    # Under {83da6326-97a6-4088-9453-a1923f573b29}: 0066 is
                    # DEVPKEY_Device_LastArrivalDate, 0067 is LastRemovalDate.
                    # This read 0067 and called it last_connected, which
                    # reports the disconnect. On this hive 20 of 22 devices
                    # carry 0066 and no 0067 - plugged in, never unplugged - so
                    # 0067 cannot be the connection time.
                    def _dev_prop(_pid):
                        if not instance_id:
                            return ""
                        for _cs in _usb_cs:
                            _pp = (f"{_cs}\\{usb_path}\\{device_id}\\{instance_id}"
                                   f"\\Properties\\{{83da6326-97a6-4088-9453-a1923f573b29}}\\{_pid}")
                            try:
                                _pv = read_registry_values(system_reg_hive, _pp)
                            except Exception:
                                continue
                            _when = _device_property_time(_pv)
                            if _when:
                                return _when
                        return ""

                    last_connected = _dev_prop("0066")

                    full_id = f"{device_id}\\{instance_id}" if instance_id else device_id
                    if not check_exists(cursor, 'USBDevices', ['device_id'], (full_id,)):
                        cursor.execute('''INSERT INTO USBDevices
                            (device_id, description, manufacturer, friendly_name, last_connected)
                            VALUES (?, ?, ?, ?, ?)''',
                            (full_id, str(description), str(manufacturer),
                             str(friendly_name), str(last_connected)))
                
                    # 2. USB Properties (USBProperties table)
                    # The properties are on the instance key, not the model key
                    # above it. Under Enum\USB a model key (VID_xxxx&PID_yyyy)
                    # holds only subkeys, so reading `values` here inserted
                    # nothing and the table was empty on every parse.
                    for prop_name, (prop_value, prop_type) in ivals.items():
                        if prop_name not in ['', None]:
                            prop_type_str = str(prop_type)
                            prop_value_str = str(prop_value)

                            # Keyed by full_id, like the USBDevices row above,
                            # so a property joins to the device it describes.
                            if not check_exists(cursor, 'USBProperties',
                                              ['device_id', 'property_name'],
                                              (full_id, prop_name)):
                                cursor.execute('''INSERT INTO USBProperties
                                    (device_id, property_name, property_value, property_type)
                                    VALUES (?, ?, ?, ?)''',
                                    (full_id, prop_name, prop_value_str, prop_type_str))
                
                # 3. USB Instances (USBInstances table)
                # Check for instance subkeys
                try:
                    reg = Registry.Registry(system_reg_hive)
                    # Try to find the device in any ControlSet
                    device_key = None
                    for cs_num in [int(active_controlset[-1]) if active_controlset[-1].isdigit() else 1, 1, 2, 3]:
                        cs_name = f"ControlSet{cs_num:03d}"
                        try:
                            full_usb_path = f"{cs_name}\\{usb_path}"
                            usb_key = reg.open(full_usb_path)
                            for subkey in usb_key.subkeys():
                                if subkey.name() == device_id:
                                    device_key = subkey
                                    break
                            if device_key:
                                break
                        except:
                            continue
                    
                    if device_key:
                        for instance_subkey in device_key.subkeys():
                            instance_id = instance_subkey.name()
                            parent_id = ""
                            service = ""
                            status = ""
                            
                            # Extract instance properties
                            for value in instance_subkey.values():
                                if value.name() == 'ParentIdPrefix':
                                    parent_id = str(value.value())
                                elif value.name() == 'Service':
                                    service = str(value.value())
                                elif value.name() == 'Status':
                                    status = str(value.value())
                            
                            if not check_exists(cursor, 'USBInstances',
                                              ['device_id', 'instance_id'],
                                              (device_id, instance_id)):
                                cursor.execute('''INSERT INTO USBInstances
                                    (device_id, instance_id, parent_id, service, status)
                                    VALUES (?, ?, ?, ?, ?)''',
                                    (device_id, instance_id, parent_id, service, status))
                except Exception as e:
                    logging.debug(f"Error processing USB instances for {device_id}: {e}")
                
            except Exception as e:
                logging.error(f"Error with USB device {device_id}: {e}")

        # 4. USB Storage devices (USBStorageDevices table)
        # Use multi-path reader with ControlSet resolution
        usbstor_path = "Enum\\USBSTOR"
        usbstor_devices = {}
        
        # Try all ControlSet paths and merge results
        for cs_num in [int(active_controlset[-1]) if active_controlset[-1].isdigit() else 1, 1, 2, 3]:
            cs_name = f"ControlSet{cs_num:03d}"
            try:
                full_path = f"{cs_name}\\{usbstor_path}"
                logging.debug(f"Checking USBSTOR path: {full_path}")
                devices = get_subkeys(system_reg_hive, full_path)
                if devices:
                    logging.debug(f"Successfully read USBSTOR devices from: {full_path}")
                    usbstor_devices.update(devices)
            except Exception as e:
                logging.debug(f"USBSTOR path not found: {full_path}")

        for device_class, device_instances in usbstor_devices.items():
            try:
                # Parse device class
                vendor_id, product_id, revision = _extract_usbstor(device_class)

                # Get serial numbers (subkeys under device class)
                try:
                    reg = Registry.Registry(system_reg_hive)
                    device_class_key = None
                    # Try to find the device class in any ControlSet
                    for cs_num in [int(active_controlset[-1]) if active_controlset[-1].isdigit() else 1, 1, 2, 3]:
                        cs_name = f"ControlSet{cs_num:03d}"
                        try:
                            full_usbstor_path = f"{cs_name}\\{usbstor_path}"
                            usbstor_key = reg.open(full_usbstor_path)
                            for subkey in usbstor_key.subkeys():
                                if subkey.name() == device_class:
                                    device_class_key = subkey
                                    break
                            if device_class_key:
                                break
                        except:
                            continue

                    if device_class_key:
                        for serial_subkey in device_class_key.subkeys():
                            serial_number = serial_subkey.name()
                            device_id = f"{device_class}\\{serial_number}"

                            friendly_name = ""
                            drive_letter = ""
                            volume_guid = ""
                            volume_name = ""
                            
                            # Extract properties from serial subkey
                            for value in serial_subkey.values():
                                if value.name() in ['FriendlyName', 'DeviceDesc']:
                                    friendly_name = str(value.value())
                                elif value.name() == 'DriveLetter':
                                    drive_letter = str(value.value())
                                elif value.name() == 'VolumeGUID':
                                    volume_guid = str(value.value())
                                elif value.name() == 'VolumeName':
                                    volume_name = str(value.value())

                            # The connection times, from the same property
                            # set the Enum\USB path reads: 0065 first install,
                            # 0066 last arrival, 0067 last removal. Offline used
                            # to write none of them, so a case parsed from an
                            # image had no USB storage timeline at all while the
                            # same machine parsed live did.
                            def _usbstor_time(_pid):
                                for _cs in _usb_cs:
                                    _pp = (f"{_cs}\\{usbstor_path}\\{device_class}"
                                           f"\\{serial_number}\\Properties"
                                           f"\\{{83da6326-97a6-4088-9453-a1923f573b29}}"
                                           f"\\{_pid}")
                                    try:
                                        _pv = read_registry_values(system_reg_hive, _pp)
                                    except Exception:
                                        continue
                                    _when = _device_property_time(_pv)
                                    if _when:
                                        return _when
                                return ""

                            first_connected = _usbstor_time("0065")
                            last_connected = _usbstor_time("0066")
                            last_removed = _usbstor_time("0067")

                            # 4a. USB Storage Devices table
                            if not check_exists(cursor, 'USBStorageDevices', ['device_id'], (device_id,)):
                                cursor.execute('''INSERT INTO USBStorageDevices
                                    (device_id, friendly_name, serial_number, vendor_id,
                                     product_id, revision, first_connected, last_connected,
                                     last_removed, parsed_at)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                                    (device_id, friendly_name, serial_number, vendor_id,
                                     product_id, revision, first_connected, last_connected,
                                     last_removed, get_current_forensic_timestamp()))
                            
                            # 5. USB Storage Volumes table (USBStorageVolumes)
                            if drive_letter or volume_guid or volume_name:
                                if not check_exists(cursor, 'USBStorageVolumes',
                                                  ['device_id', 'volume_guid'],
                                                  (device_id, volume_guid)):
                                    cursor.execute('''INSERT INTO USBStorageVolumes
                                        (device_id, volume_guid, volume_name, drive_letter, parsed_at)
                                        VALUES (?, ?, ?, ?, ?)''',
                                        (device_id, volume_guid, volume_name, drive_letter,
                                         get_current_forensic_timestamp()))

                except Exception as e:
                    logging.error(f"Error processing USB storage {device_class}: {e}")

            except Exception as e:
                logging.error(f"Error with USBSTOR: {e}")

        conn.commit()
        print(f"[OK] USB device timeline collected: {len(usb_devices)} devices, {len(usbstor_devices)} storage classes\n")
    except Exception as e:
        logging.error(f"Error with USB: {e}")

    # PHASE 5: BROWSER HISTORY & SOFTWARE INVENTORY (NEW)
    print("[SOFTWARE] Collecting software and browser history...")
    try:
        # Browser History (IE TypedURLs)
        for ntuser_idx, Ntuser_reg_hive in enumerate(ntuser_hives):
            # Whose hive is this? Rows below are attributed to this user.
            _hive_user = user_identity.display_owner(Ntuser_reg_hive, _identity_accounts)
            try:
                typedurls_path = "Software\\Microsoft\\Internet Explorer\\TypedURLs"
                typedurls_values = read_registry_values(Ntuser_reg_hive, typedurls_path)
                # TypedURLsTime holds an 8-byte FILETIME per urlN - the only time
                # this artifact records. Absent before Windows 8, so a missing
                # key is normal, not an error.
                typedurls_time = read_registry_values(
                    Ntuser_reg_hive, "Software\\Microsoft\\Internet Explorer\\TypedURLsTime")

                for name, (data, value_type) in typedurls_values.items():
                    try:
                        url = str(data)
                        when = ''
                        _t = typedurls_time.get(name)
                        if _t and isinstance(_t[0], bytes):
                            try:
                                when = registry_binary_parser.parse_filetime(_t[0]) or ''
                            except Exception as e:
                                logging.debug(f"TypedURLsTime {name}: {e}")
                        # Keyed by user: two accounts can type the same URL, and
                        # both are evidence. On url alone the second hive's row
                        # was dropped, and the table could not say whose it was -
                        # _hive_user was computed here and never used.
                        if url and not check_exists(cursor, 'BrowserHistory',
                                                    ['url', 'user_name'],
                                                    (url, _hive_user)):
                            cursor.execute('''INSERT INTO BrowserHistory
                                (browser, url, title, visit_count, last_visit, parsed_at, user_name)
                                VALUES (?, ?, ?, ?, ?, ?, ?)''',
                                ('Internet Explorer', url, '', 0, when,
                                 get_current_forensic_timestamp(), _hive_user))
                    except Exception as e:
                        logging.error(f"Error with BrowserHistory entry: {e}")
            except Exception as e:
                logging.debug(f"TypedURLs unavailable in NTUSER[{ntuser_idx}]: {e}")

        # Installed Software (64-bit & 32-bit)
        uninstall_paths = [
            (Software_reg_hive, "Microsoft\\Windows\\CurrentVersion\\Uninstall"),
            (Software_reg_hive, "WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall")
        ]

        for hive, path in uninstall_paths:
            try:
                software_subkeys = get_subkeys(hive, path)
                for software_name, values in software_subkeys.items():
                    try:
                        display_name = values.get('DisplayName', ('', 'REG_SZ'))[0] if 'DisplayName' in values else software_name
                        display_version = values.get('DisplayVersion', ('', 'REG_SZ'))[0] if 'DisplayVersion' in values else ''
                        publisher = values.get('Publisher', ('', 'REG_SZ'))[0] if 'Publisher' in values else ''
                        install_date = values.get('InstallDate', ('', 'REG_SZ'))[0] if 'InstallDate' in values else ''
                        install_location = values.get('InstallLocation', ('', 'REG_SZ'))[0] if 'InstallLocation' in values else ''
                        uninstall_string = values.get('UninstallString', ('', 'REG_SZ'))[0] if 'UninstallString' in values else ''

                        display_name_str = str(display_name)
                        if display_name_str and not check_exists(cursor, 'InstalledSoftware', ['display_name'], (display_name_str,)):
                            # parsed_at is the parse time. EstimatedSize was
                            # appended to it as JSON, which is not what the live
                            # parser does and made the column unsortable as a
                            # time. InstalledSoftware has no size column, so the
                            # value is simply not recorded rather than recorded
                            # somewhere it does not belong.
                            ts = get_current_forensic_timestamp()
                            cursor.execute('''INSERT INTO InstalledSoftware
                                (display_name, display_version, publisher, install_date, install_location, uninstall_string, parsed_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?)''',
                                (display_name_str, str(display_version), str(publisher),
                                 registry_binary_parser.normalise_install_date(install_date),
                                 str(install_location), str(uninstall_string), ts))

                            # Two SuspiciousIndicators verdicts were written here
                            # ("no publisher", "potential hacking/malware tool").
                            # The publisher field is already stored above, so the
                            # fact survives; the keyword rule matched software by
                            # name alone and accused legitimate tools.

                    except Exception as e:
                        logging.error(f"Error with software {software_name}: {e}")

            except Exception as e:
                logging.debug(f"Uninstall path unavailable: {path}")

        conn.commit()
        print("[OK] Software and browser history collected\n")
    except Exception as e:
        logging.error(f"Error with software: {e}")

    # PHASE 5: SYSTEM SERVICES (NEW)
    print("[SERVICES] Collecting system services...")
    try:
        # Get active ControlSet for this system
        active_controlset = get_active_controlset(system_reg_hive)
        logging.info(f"Using active ControlSet for System Services extraction: {active_controlset}")
        
        # Use multi-path reader with ControlSet resolution
        services_path = "Services"
        services_subkeys = {}
        
        # Try all ControlSet paths and merge results
        for cs_num in [int(active_controlset[-1]) if active_controlset[-1].isdigit() else 1, 1, 2, 3]:
            cs_name = f"ControlSet{cs_num:03d}"
            try:
                full_path = f"{cs_name}\\{services_path}"
                logging.debug(f"Checking System Services path: {full_path}")
                services = get_subkeys(system_reg_hive, full_path)
                if services:
                    logging.debug(f"Successfully read System Services from: {full_path}")
                    services_subkeys.update(services)
            except Exception as e:
                logging.debug(f"System Services path not found: {full_path}")

        for service_name, values in services_subkeys.items():
            try:
                # No DisplayName means the service has none. Falling back to the
                # key name invented a display name the registry does not hold, on
                # 130 of 874 services, and disagreed with the live parser on every
                # one of them.
                display_name = values.get('DisplayName', ('', 'REG_SZ'))[0] if 'DisplayName' in values else ''
                description = values.get('Description', ('', 'REG_SZ'))[0] if 'Description' in values else ''
                image_path = values.get('ImagePath', ('', 'REG_SZ'))[0] if 'ImagePath' in values else ''
                start_type = values.get('Start', (0, 'REG_DWORD'))[0] if 'Start' in values else 0
                service_type = values.get('Type', (0, 'REG_DWORD'))[0] if 'Type' in values else 0
                error_control = values.get('ErrorControl', (0, 'REG_DWORD'))[0] if 'ErrorControl' in values else 0

                # Status names the Start type, matching the live parser. "Active"
                # / "Inactive" was a second vocabulary for the same field, so all
                # 874 rows disagreed between the two parsers, and it also claimed
                # a running state that a registry hive cannot tell you.
                status = {0: "Boot", 2: "Auto Start", 3: "Manual",
                          4: "Disabled"}.get(start_type, "Unknown")

                if not check_exists(cursor, 'SystemServices', ['service_name'], (service_name,)):
                    # description holds the service's description and nothing
                    # else. A JSON fragment carrying start_type_text was appended
                    # to all 874 rows - start_type is already its own column, so
                    # this restated it while corrupting the description an analyst
                    # reads.
                    cursor.execute('''INSERT INTO SystemServices
                        (service_name, display_name, description, image_path, start_type, service_type,
                         error_control, status, parsed_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (service_name, str(display_name), str(description), str(image_path),
                         int(start_type), int(service_type), int(error_control),
                         status, get_current_forensic_timestamp()))

                    # Check for suspicious services
                    image_path_str = str(image_path).lower()
                    display_name_str = str(display_name).lower()
                    description_str = str(description).lower()

                    if start_type == 2:  # AutoStart
                        risk_level = 1
                        # A SuspiciousIndicators verdict was written here. It
                        # produced 71 "service executable in suspicious path"
                        # rows on a reference image; the service, its image path
                        # and its start type are all kept in SystemServices.

            except Exception as e:
                logging.error(f"Error with service {service_name}: {e}")

        conn.commit()
        print("[OK] System services collected\n")
    except Exception as e:
        logging.error(f"Error with services: {e}")

    # PHASE 6: NETWORK CONFIGURATION (NEW)
    print("[NETWORK] Collecting network configuration and history...")
    try:
        # Network List (Network connection history)
        # Extract from ALL three paths: Profiles, Signatures\Unmanaged, Signatures\Managed
        network_list_paths = [
            "Microsoft\\Windows NT\\CurrentVersion\\NetworkList\\Profiles",
            "Microsoft\\Windows NT\\CurrentVersion\\NetworkList\\Signatures\\Unmanaged",
            "Microsoft\\Windows NT\\CurrentVersion\\NetworkList\\Signatures\\Managed"
        ]
        
        # Both key trees, kept so they can be joined on ProfileGuid after
        # the loop. Signatures\\Unmanaged holds the gateway MAC and the DNS
        # suffix; Profiles holds the name, the category and the dates; and a
        # table with one row per value keeps them on separate rows forever.
        _nl_profiles = {}
        _nl_signatures = []

        for network_list_path in network_list_paths:
            _nl_kind = ("profile" if network_list_path.rstrip(chr(92)).lower()
                        .endswith("profiles") else "signature")
            try:
                logging.debug(f"Checking Network Lists path: {network_list_path}")
                network_profiles = get_subkeys(Software_reg_hive, network_list_path)
                
                if network_profiles:
                    logging.debug(f"Successfully read Network Lists from: {network_list_path}")
            
                for profile_guid, values in network_profiles.items():
                    try:
                        if _nl_kind == "profile":
                            _nl_profiles[str(profile_guid).strip().lower()] = (
                                profile_guid, values, network_list_path)
                        else:
                            _nl_signatures.append(
                                (profile_guid, values, network_list_path))
                        # A Signatures key has no ProfileName - it names the
                        # network in FirstNetwork instead. Reading only
                        # ProfileName left network_name empty on all 24 signature
                        # rows while the live parser filled them, so the same
                        # network was named in one parser and anonymous in the
                        # other.
                        profile_name = values.get('ProfileName', ('', 'REG_SZ'))[0] if 'ProfileName' in values else ''
                        if not profile_name and 'FirstNetwork' in values:
                            profile_name = values['FirstNetwork'][0]
                        date_created = values.get('DateCreated', ('', 'REG_BINARY'))[0] if 'DateCreated' in values else ''
                        date_last_connected = values.get('DateLastConnected', ('', 'REG_BINARY'))[0] if 'DateLastConnected' in values else ''
                        
                        default_gateway_mac = values.get('DefaultGatewayMac', ('', 'REG_BINARY'))[0] if 'DefaultGatewayMac' in values else ''
                        
                        # Parse binary timestamps (SYSTEMTIME 16 bytes)
                        date_created_str = ""
                        date_last_connected_str = ""
                        
                        if isinstance(date_created, bytes) and len(date_created) >= 16:
                            try:
                                date_created_str = registry_binary_parser.parse_systemtime(date_created)
                            except:
                                pass
                        
                        if isinstance(date_last_connected, bytes) and len(date_last_connected) >= 16:
                            try:
                                date_last_connected_str = registry_binary_parser.parse_systemtime(date_last_connected)
                            except:
                                pass
                        
                        formatted_mac = ''
                        if default_gateway_mac:
                            formatted_mac = (registry_binary_parser.format_mac_address(default_gateway_mac)
                                             if isinstance(default_gateway_mac, bytes)
                                             else str(default_gateway_mac))

                        # Populate the Network_list table.
                        #
                        # Guarded: the table carries no UNIQUE or PRIMARY KEY, so
                        # OR IGNORE was a no-op and every re-parse appended the
                        # whole profile set again without raising anything.
                        # The enrichment columns repeat the profile-level facts on
                        # each row so a query can filter without re-joining, which
                        # is what the live parser already does.
                        # Network_list is a raw per-value table: one row for
                        # every value the key holds, under the name the key uses
                        # for it, with the raw data. That is what the live parser
                        # writes, and three things here disagreed with it.
                        #
                        # A hand-picked list of six names recorded 28 rows where
                        # live recorded 52 - Description, DnsSuffix, FirstNetwork,
                        # Managed, NameType, ProfileGuid and Source were absent.
                        # "SSID" was written as a second name for FirstNetwork,
                        # which is not a value this key has. And the guard
                        # skipped anything falsy, so Managed = 0 - a real DWORD
                        # saying the network is unmanaged - was dropped for
                        # looking like nothing.
                        #
                        # Decoded forms belong in the enrichment columns beside
                        # the raw value, not in `data`. The two SYSTEMTIME blobs
                        # are the documented exception the live parser also makes.
                        for _vn, _vp in values.items():
                            _vd, _vt = _vp if isinstance(_vp, tuple) else (_vp, 'REG_SZ')
                            if (str(_vn).lower() in ('datecreated', 'datelastconnected')
                                    and isinstance(_vd, bytes) and len(_vd) >= 16):
                                try:
                                    _dec = registry_binary_parser.parse_systemtime(_vd)
                                    if _dec:
                                        _vd = _dec
                                except Exception:
                                    pass
                            if check_exists(cursor, 'Network_list',
                                            ['subkey', 'name', 'data', 'type'],
                                            (str(profile_guid), str(_vn), str(_vd), str(_vt))):
                                continue
                            cursor.execute(
                                'INSERT INTO Network_list (subkey, name, data, '
                                'decoded, type, network_name, connection_date, '
                                'gateway_mac, parsed_at) '
                                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                                (str(profile_guid), str(_vn), str(_vd),
                                 registry_binary_parser.render_registry_value(
                                     'networklist', _vn,
                                     _vp[0] if isinstance(_vp, tuple) else _vp,
                                     _vt),
                                 str(_vt),
                                 str(profile_name), date_last_connected_str,
                                 formatted_mac,
                                 get_current_forensic_timestamp()))

                    except Exception as e:
                        logging.error(f"Error with network profile {profile_guid}: {e}")
            except Exception as e:
                logging.debug(f"NetworkList path unavailable: {network_list_path}")


        # --- one row per network, joined on ProfileGuid --------------------
        def _nlv(values, want):
            for _n, _p in (values or {}).items():
                if str(_n).lower() == want:
                    return _p[0] if isinstance(_p, tuple) else _p
            return None

        def _nli(values, want):
            try:
                return int(_nlv(values, want))
            except (TypeError, ValueError):
                return None

        try:
            _seen = set()
            _rows = []
            for _sig, _sv, _sp in _nl_signatures:
                _guid = _nlv(_sv, 'profileguid')
                _key = str(_guid).strip().lower() if _guid else ""
                _pr = _nl_profiles.get(_key)
                if _key:
                    _seen.add(_key)
                # Both keys, each as its own full path. Concatenating a
                # name that can be empty is how the live parser first came to
                # read the PARENT key's write time for every row - a trailing
                # separator opens the parent and raises nothing.
                _rows.append((_guid, _sig, _sv, _pr[1] if _pr else {},
                              (_pr[2] + chr(92) + str(_pr[0])) if _pr else "",
                              _sp + chr(92) + str(_sig)))
            # A profile with no signature is still a network this machine
            # joined; dropping it would make the summary hold fewer networks
            # than the registry does.
            for _key, (_guid, _pv, _pp) in _nl_profiles.items():
                if _key not in _seen:
                    _rows.append((_guid, "", {}, _pv,
                                  _pp + chr(92) + str(_guid), ""))

            for _guid, _sig, _sv, _pv, _profile_key, _signature_key in _rows:
                _mac = _nlv(_sv, 'defaultgatewaymac')
                _cat = _nli(_pv, 'category')
                _nt = _nli(_pv, 'nametype')
                _mg = _nli(_pv, 'managed')
                _cr = _nlv(_pv, 'datecreated')
                _lc = _nlv(_pv, 'datelastconnected')
                _pn = _nlv(_pv, 'profilename')
                _ds = _nlv(_sv, 'dnssuffix')
                _desc = _nlv(_pv, 'description') or _nlv(_sv, 'description')
                # The profile key carries the dates, so its write time is
                # what bounds this row.
                _kp = _profile_key or _signature_key
                _written = (key_last_write(Software_reg_hive, _profile_key)
                            if _profile_key else "")
                if not _written and _signature_key:
                    _written = key_last_write(Software_reg_hive, _signature_key)
                if check_exists(cursor, 'NetworkProfiles',
                                ['profile_guid', 'signature'],
                                (str(_guid or ""), str(_sig or ""))):
                    continue
                cursor.execute(
                    'INSERT INTO NetworkProfiles (profile_guid, profile_name, '
                    'description, signature, first_network, gateway_mac, '
                    'dns_suffix, category, category_label, name_type, '
                    'name_type_label, managed, managed_label, source, '
                    'date_created, date_last_connected, key_path, '
                    'last_written, time_basis, parsed_at) VALUES '
                    '(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (str(_guid or ""),
                     str(_pn) if _pn is not None else None,
                     str(_desc) if _desc is not None else None,
                     str(_sig or ""),
                     str(_nlv(_sv, 'firstnetwork') or "") or None,
                     (registry_binary_parser.format_mac_address(_mac)
                      if isinstance(_mac, bytes) and len(_mac) >= 6 else None),
                     # "<none>" is what Windows writes when a network has no
                     # DNS suffix. Carried through as found: it is the
                     # registry's answer, not a missing value.
                     str(_ds) if _ds is not None else None,
                     _cat,
                     registry_binary_parser.network_category_label(_cat)
                     if _cat is not None else None,
                     _nt,
                     registry_binary_parser.network_name_type_label(_nt)
                     if _nt is not None else None,
                     _mg,
                     registry_binary_parser.network_managed_label(_mg)
                     if _mg is not None else None,
                     _nli(_sv, 'source'),
                     registry_binary_parser.parse_systemtime(_cr)
                     if isinstance(_cr, bytes) else None,
                     registry_binary_parser.parse_systemtime(_lc)
                     if isinstance(_lc, bytes) else None,
                     _kp, _written,
                     'key upper bound' if _written else None,
                     get_current_forensic_timestamp()))
        except Exception as _exc:
            logging.error("NetworkProfiles could not be built: %s", _exc)

        # Network Interfaces
        # Get active ControlSet for this system
        active_controlset = get_active_controlset(system_reg_hive)
        logging.info(f"Using active ControlSet for Network Interfaces extraction: {active_controlset}")
        
        # Use multi-path reader with ControlSet resolution
        network_interfaces_path = "Services\\Tcpip\\Parameters\\Interfaces"
        network_interfaces = {}
        
        # Try all ControlSet paths and merge results
        for cs_num in [int(active_controlset[-1]) if active_controlset[-1].isdigit() else 1, 1, 2, 3]:
            cs_name = f"ControlSet{cs_num:03d}"
            try:
                full_path = f"{cs_name}\\{network_interfaces_path}"
                logging.debug(f"Checking Network Interfaces path: {full_path}")
                interfaces = get_subkeys(system_reg_hive, full_path)
                if interfaces:
                    logging.debug(f"Successfully read Network Interfaces from: {full_path}")
                    network_interfaces.update(interfaces)
            except Exception as e:
                logging.debug(f"Network Interfaces path not found: {full_path}")

        # Raw layer: every value verbatim, keyed by interface. The structured
        # table below keeps only the fields it understands, so without this the
        # offline database loses everything else the key held.
        def _ni_text(v):
            """A raw value as text, rendering MULTI_SZ the way the live parser does.

            str() on a MULTI_SZ list wrote a Python list literal into the raw
            dump, and the two readers disagree about what is in that list -
            winreg drops the NUL terminators, python-registry keeps them - so
            the same interface read "['192.168.56.1']" live and
            "['192.168.56.1', '', '']" from the hive. Same evidence, two
            spellings, on every MULTI_SZ value of every interface.
            """
            if isinstance(v, (list, tuple)):
                items = [str(x) for x in v]
                while items and items[-1] == "":
                    items.pop()
                return ", ".join(items)
            return str(v)

        for interface_id, values in network_interfaces.items():
            for _vn, _vt in values.items():
                try:
                    _d, _t = _vt if isinstance(_vt, tuple) else (_vt, '')
                    if not check_exists(cursor, 'network_interfaces',
                                        ['subkey', 'name'],
                                        (str(interface_id), str(_vn))):
                        cursor.execute(
                            'INSERT INTO network_interfaces '
                            '(subkey, name, row_data, decoded, type) '
                            'VALUES (?, ?, ?, ?, ?)',
                            (str(interface_id), str(_vn), _ni_text(_d),
                             registry_binary_parser.render_registry_value(
                                 'network_interfaces', _vn, _d, _t),
                             str(_t)))
                except Exception as e:
                    logging.debug(f"raw network_interfaces {interface_id}/{_vn}: {e}")

        # Adapter MAC overrides, keyed by the interface GUID that ties an
        # adapter to its Tcpip interface key. Built once: the class key holds
        # every adapter the machine has ever had, and re-walking it per
        # interface would be ten walks for one answer.
        _mac_overrides = {}
        try:
            _cs = active_controlset or "ControlSet001"
            _cls_base = (_cs + chr(92) + "Control" + chr(92) + "Class" + chr(92)
                         + registry_binary_parser.ADAPTER_CLASS_GUID)
            for _adapter in (get_subkeys(system_reg_hive, _cls_base) or []):
                if not str(_adapter).isdigit():
                    continue
                _av = read_registry_values(
                    system_reg_hive, _cls_base + chr(92) + str(_adapter)) or {}

                def _val(name):
                    item = _av.get(name)
                    if item is None:
                        return ""
                    return item[0] if isinstance(item, (tuple, list)) else item

                _guid = _val("NetCfgInstanceId")
                _mac = registry_binary_parser.normalise_mac(_val("NetworkAddress"))
                if _guid and _mac:
                    _mac_overrides[str(_guid).lower()] = _mac
        except Exception as _exc:
            logging.debug("adapter MAC overrides: %s", _exc)
        if _mac_overrides:
            print("[OK] %d network adapter(s) carry a MAC override - a MAC in "
                  "the registry is one somebody set" % len(_mac_overrides))

        for interface_id, values in network_interfaces.items():
            try:
                # Assigned below, once _first exists. The value names are
                # IPAddress and SubnetMask; 'static IPAddress' is not a registry
                # value at all, so a statically configured interface matched
                # nothing and both columns stayed empty with no error.
                ip_address = subnet_mask = ''
                # First non-empty wins, static before DHCP - the way Windows
                # itself resolves them. The static NameServer/DefaultGateway
                # values exist on almost every interface but are EMPTY on a DHCP
                # client, so a plain `in values` test picked the empty string and
                # left the column blank. 'DhcpNameServers' was also misspelled
                # (the value is singular), so it never matched anything at all.
                def _first(*names):
                    for _n in names:
                        _v = values.get(_n)
                        if isinstance(_v, tuple):
                            _v = _v[0]
                        if _v not in (None, ''):
                            if isinstance(_v, (list, tuple)):
                                items = [str(x) for x in _v]
                                # Trailing empties are the MULTI_SZ terminators;
                                # joining them produced "192.168.100.1, , ".
                                while items and items[-1] == "":
                                    items.pop()
                                if not items:
                                    continue
                                return ", ".join(items)
                            return _v
                    return ''

                ip_address = _first('IPAddress', 'DhcpIPAddress')
                subnet_mask = _first('SubnetMask', 'DhcpSubnetMask')
                default_gateway = _first('DefaultGateway', 'static DefaultGateway',
                                         'DhcpDefaultGateway')
                # Absent EnableDHCP is not evidence of DHCP. Defaulting to 1
                # asserted something the hive does not say, and disagreed with
                # the live parser, which defaults to 0.
                dhcp_enabled = values.get('EnableDHCP', (0, 'REG_DWORD'))[0] if 'EnableDHCP' in values else 0
                dhcp_server = values.get('DhcpServer', ('', 'REG_SZ'))[0] if 'DhcpServer' in values else ''
                dns_servers = _first('NameServer', 'DhcpNameServer', 'DhcpNameServers')
                # The DNS suffix the interface was given. The user asked for
                # it and it existed only as a raw row.
                dns_suffix = _first('Domain', 'DhcpDomain')
                # The gateway's own hardware address, and a second independent
                # record of what NetworkList keeps as DefaultGatewayMac. It is
                # the GATEWAY's MAC - deliberately not mac_address, which means
                # this adapter's own overridden address.
                _gwhw = values.get('DhcpGatewayHardware')
                if isinstance(_gwhw, tuple):
                    _gwhw = _gwhw[0]
                _gw = registry_binary_parser.parse_dhcp_gateway_hardware(_gwhw)
                lease_obtained = registry_binary_parser.unix_seconds_label(
                    _first('LeaseObtainedTime'))
                lease_expires = registry_binary_parser.unix_seconds_label(
                    _first('LeaseTerminatesTime'))
                mac_address = _mac_overrides.get(str(interface_id).lower(), '')

                # An interface with no IP is still an interface, and its DNS
                # servers and gateway can still matter. Gating on ip_address
                # dropped six of this machine's ten interfaces, so the offline
                # parser reported four where the live one reported ten.
                if not check_exists(cursor, 'NetworkInterfacesInfo', ['interface_id'], (interface_id,)):
                    cursor.execute('''INSERT INTO NetworkInterfacesInfo
                        (interface_id, ip_address, subnet_mask, default_gateway,
                         dhcp_enabled, dhcp_server, dns_servers, mac_address,
                         gateway_ip, gateway_hardware_mac, dns_suffix,
                         lease_obtained, lease_expires, parsed_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (interface_id, str(ip_address), str(subnet_mask), str(default_gateway),
                         int(dhcp_enabled), str(dhcp_server), str(dns_servers),
                         mac_address, _gw['gateway_ip'] or None,
                         _gw['gateway_mac'] or None, str(dns_suffix) or None,
                         lease_obtained or None, lease_expires or None,
                         get_current_forensic_timestamp()))
            except Exception as e:
                logging.error(f"Error with network interface {interface_id}: {e}")

        conn.commit()
        print("[OK] Network configuration collected\n")
    except Exception as e:
        logging.error(f"Error with network: {e}")
    
    # PHASE 6.5: COMPUTER NAME AND TIMEZONE (NEW)
    print("[SYSTEM] Collecting computer name and timezone information...")
    try:
        # Get active ControlSet for this system
        active_controlset = get_active_controlset(system_reg_hive)
        logging.info(f"Using active ControlSet: {active_controlset}")
        
        # Computer Name
        try:
            # Use multi-path reader with ControlSet resolution
            computer_name_values, successful_paths = read_registry_multi_path(
                system_reg_hive,
                "Control\\ComputerName\\ComputerName",
                controlset_dependent=True,
                active_controlset=active_controlset
            )
            
            computer_name = computer_name_values.get('ComputerName', ('', 'REG_SZ'))[0] if 'ComputerName' in computer_name_values else ''
            
            if successful_paths:
                logging.debug(f"Extracted Computer Name from {len(successful_paths)} path(s): {successful_paths}")
            
            # Get additional system info from SOFTWARE hive
            current_version_path = "Microsoft\\Windows NT\\CurrentVersion"
            current_version_values = read_registry_values(Software_reg_hive, current_version_path)
            
            registered_owner = current_version_values.get('RegisteredOwner', ('', 'REG_SZ'))[0] if 'RegisteredOwner' in current_version_values else ''
            registered_organization = current_version_values.get('RegisteredOrganization', ('', 'REG_SZ'))[0] if 'RegisteredOrganization' in current_version_values else ''
            product_id = current_version_values.get('ProductId', ('', 'REG_SZ'))[0] if 'ProductId' in current_version_values else ''
            install_date = current_version_values.get('InstallDate', (0, 'REG_DWORD'))[0] if 'InstallDate' in current_version_values else 0
            
            # Convert install_date from Unix timestamp to ISO format
            install_date_str = ""
            if install_date and install_date > 0:
                try:
                    # Convert Windows timestamp to readable date (ensure UTC)
                    install_date_str = format_forensic_timestamp(datetime.datetime.fromtimestamp(int(install_date), tz=datetime.timezone.utc))
                except:
                    pass
            
            # Same rule as above: parsed_at holds the parse time only. The
            # product name was appended to it as JSON.
            ts = get_current_forensic_timestamp()
            if not check_exists(cursor, 'ComputerNameInfo', ['computer_name'], (str(computer_name),)):
                cursor.execute('''INSERT OR IGNORE INTO ComputerNameInfo
                    (computer_name, registered_owner, registered_organization, product_id, installation_date, parsed_at)
                    VALUES (?, ?, ?, ?, ?, ?)''',
                    (str(computer_name), str(registered_owner), str(registered_organization),
                     str(product_id), install_date_str, ts))
            
            # Also populate the raw computer_Name table (column is row_data,
            # not data - the old name silently discarded every row).
            #
            # Every value of the key, not just ComputerName. The key also holds
            # a default value - "mnmsrvc" on this machine - which the live
            # parser records and this one dropped, because it wrote one
            # hardcoded name rather than what the key contains. Same defect as
            # time_zone and Network_list. _default_name normalises
            # python-registry's "(default)" to the empty name winreg reports,
            # so the two parsers agree on what to call it.
            for _cn_name, _cn_val in (computer_name_values or {}).items():
                _cn_d, _cn_t = _cn_val if isinstance(_cn_val, tuple) else (_cn_val, 'REG_SZ')
                _cn_name = _default_name(_cn_name)
                if isinstance(_cn_d, bytes):
                    _cn_d = _cn_d.hex()
                if not check_exists(cursor, 'computer_Name',
                                    ['name', 'row_data', 'type'],
                                    (_cn_name, str(_cn_d), str(_cn_t))):
                    cursor.execute('INSERT INTO computer_Name (name, row_data, type) VALUES (?, ?, ?)',
                                   (_cn_name, str(_cn_d), str(_cn_t)))
        except Exception as e:
            logging.debug(f"ComputerName path unavailable: {e}")
        
        # TimeZone Information
        try:
            # Use multi-path reader with ControlSet resolution
            timezone_values, successful_paths = read_registry_multi_path(
                system_reg_hive,
                "Control\\TimeZoneInformation",
                controlset_dependent=True,
                active_controlset=active_controlset
            )
            
            time_zone_name = timezone_values.get('TimeZoneKeyName', ('', 'REG_SZ'))[0] if 'TimeZoneKeyName' in timezone_values else ''
            standard_name = timezone_values.get('StandardName', ('', 'REG_SZ'))[0] if 'StandardName' in timezone_values else ''
            daylight_name = timezone_values.get('DaylightName', ('', 'REG_SZ'))[0] if 'DaylightName' in timezone_values else ''
            bias = timezone_values.get('Bias', (0, 'REG_DWORD'))[0] if 'Bias' in timezone_values else 0
            active_time_bias = timezone_values.get('ActiveTimeBias', (0, 'REG_DWORD'))[0] if 'ActiveTimeBias' in timezone_values else 0
            
            if successful_paths:
                logging.debug(f"Extracted Time Zone from {len(successful_paths)} path(s): {successful_paths}")
            
            daylight_bias = timezone_values.get('DaylightBias', (0, 'REG_DWORD'))[0] if 'DaylightBias' in timezone_values else 0
            standard_start = timezone_values.get('StandardStart', (b'', 'REG_BINARY'))[0] if 'StandardStart' in timezone_values else b''
            daylight_start = timezone_values.get('DaylightStart', (b'', 'REG_BINARY'))[0] if 'DaylightStart' in timezone_values else b''
            dynamic_disabled = timezone_values.get('DynamicDaylightTimeDisabled', (None, 'REG_DWORD'))[0] if 'DynamicDaylightTimeDisabled' in timezone_values else None

            # StandardName and DaylightName are MUI references - the readable
            # text is in this evidence's own SOFTWARE hive, under
            # Time Zones\\<TimeZoneKeyName>. Read from the image rather than
            # resolved through a Windows API, which would answer about the
            # analyst's machine and its language.
            def _tz_read_offline(path):
                try:
                    _vals = read_registry_values(
                        Software_reg_hive,
                        path.split("SOFTWARE" + chr(92), 1)[-1])
                    return {_k: (_v[0] if isinstance(_v, tuple) else _v)
                            for _k, _v in (_vals or {}).items()}
                except Exception:
                    return {}

            resolved_tz = registry_binary_parser.resolve_time_zone_names(
                _tz_read_offline, str(time_zone_name))
            std_rule = registry_binary_parser.parse_tz_transition_rule(standard_start)
            dlt_rule = registry_binary_parser.parse_tz_transition_rule(daylight_start)

            # Cross-checked against TZI, which stores the same two transitions
            # in the documented SYSTEMTIME order. The Start values put
            # wDayOfWeek somewhere else, and read the documented way they give
            # an hour of 59 - wrong, and silent about it.
            agrees_tzi = ""
            try:
                _tzi = _tz_read_offline("%s%s%s" % (
                    registry_binary_parser.TIME_ZONES_KEY, chr(92),
                    time_zone_name)).get("TZI")
                if _tzi:
                    _checks = [
                        registry_binary_parser.tz_rules_agree(
                            std_rule,
                            registry_binary_parser.tz_rule_from_tzi(_tzi, False)),
                        registry_binary_parser.tz_rules_agree(
                            dlt_rule,
                            registry_binary_parser.tz_rule_from_tzi(_tzi, True)),
                    ]
                    if all(_c is True for _c in _checks):
                        agrees_tzi = "yes"
                    elif any(_c is False for _c in _checks):
                        agrees_tzi = "NO - the Start values and TZI disagree"
            except Exception as _exc:
                logging.debug("TZI cross-check unavailable: %s", _exc)

            _signed = registry_binary_parser.signed_bias(bias)
            if not check_exists(cursor, 'TimeZoneInfo', ['time_zone_name'], (str(time_zone_name),)):
                cursor.execute('''INSERT OR IGNORE INTO TimeZoneInfo
                    (time_zone_name, standard_name, daylight_name, bias,
                     active_time_bias, daylight_bias, utc_offset, display_name,
                     standard_name_raw, daylight_name_raw, standard_start_rule,
                     daylight_start_rule, dynamic_dst_disabled, agrees_with_tzi,
                     parsed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (str(time_zone_name),
                     resolved_tz["standard_name"] or str(standard_name),
                     resolved_tz["daylight_name"] or str(daylight_name),
                     _signed,
                     registry_binary_parser.signed_bias(active_time_bias),
                     registry_binary_parser.signed_bias(daylight_bias),
                     registry_binary_parser.utc_offset_label(_signed),
                     resolved_tz["display_name"],
                     str(standard_name), str(daylight_name),
                     std_rule["rule"], dlt_rule["rule"],
                     registry_binary_parser.render_registry_value(
                         'timezone', 'DynamicDaylightTimeDisabled',
                         dynamic_disabled, 4)
                     if dynamic_disabled is not None else "",
                     agrees_tzi,
                     get_current_forensic_timestamp()))
            # Shell items carry DOS date/time, which is this machine's local
            # wall clock with no zone in it. Hand the decoder the offset so
            # those readings become real UTC instead of being relabelled.
            _applied = registry_binary_parser.set_evidence_bias(bias)
            print("[OK] Evidence timezone: %s (UTC%s) - shell item times "
                  "converted" % (time_zone_name,
                                 registry_binary_parser.utc_offset_label(bias))
                  if _applied else
                  "[--] No usable timezone bias - shell item times stay on the "
                  "evidence machine's local clock")
            
            # Also populate the raw time_zone table (column is row_data).
            #
            # Every value, not a hardcoded two. This is a raw name/row_data dump
            # and the live parser writes one row per value, so pinning it to
            # TimeZoneKeyName and StandardName gave 2 rows offline against 10
            # live from the same key - Bias, ActiveTimeBias, DaylightBias and
            # the rest simply vanished.
            for _tz_name, _tz_pair in timezone_values.items():
                _tz_data, _tz_type = (_tz_pair if isinstance(_tz_pair, tuple)
                                      else (_tz_pair, 'REG_SZ'))
                if check_exists(cursor, 'time_zone', ['name'], (str(_tz_name),)):
                    continue
                cursor.execute(
                    'INSERT INTO time_zone (name, row_data, decoded, type) '
                    'VALUES (?, ?, ?, ?)',
                    (str(_tz_name), str(_tz_data),
                     registry_binary_parser.render_registry_value(
                         'timezone', _tz_name, _tz_data, _tz_type),
                     str(_tz_type)))

            # The MUI names only become readable once the SOFTWARE hive has
            # been consulted, which happens above - but the rows they belong to
            # are written here. Filling them before the insert updated nothing.
            for _col, _val in (("StandardName", resolved_tz["standard_name"]),
                               ("DaylightName", resolved_tz["daylight_name"]),
                               ("TimeZoneKeyName", resolved_tz["display_name"])):
                if _val:
                    cursor.execute(
                        'UPDATE time_zone SET decoded = ? WHERE name = ? '
                        'AND (decoded IS NULL OR decoded = ?)', (_val, _col, ""))
        except Exception as e:
            logging.debug(f"TimeZone path unavailable: {e}")
        
        # User Profiles
        try:
            profile_list_path = "Microsoft\\Windows NT\\CurrentVersion\\ProfileList"
            profile_list_subkeys = get_subkeys(Software_reg_hive, profile_list_path)
            
            for user_sid, values in profile_list_subkeys.items():
                try:
                    profile_image_path = values.get('ProfileImagePath', ('', 'REG_SZ'))[0] if 'ProfileImagePath' in values else ''
                    # State is a bitmask, and profile_loaded is a 0/1 flag that
                    # user_identity.py also writes as 0/1. Storing the raw State
                    # here put a bitmask in a boolean column, so the two parsers
                    # disagreed on every row of a four-row table. Same convention
                    # as the live parser: State 0 is the loaded profile.
                    _state_raw = values.get('State', (0, 'REG_DWORD'))[0] if 'State' in values else 0
                    try:
                        profile_loaded = 1 if int(_state_raw) == 0 else 0
                    except (TypeError, ValueError):
                        profile_loaded = 0
                    
                    # Extract username from profile path
                    username = ""
                    if profile_image_path:
                        # Extract last part of path (e.g., C:\Users\John -> John)
                        username = profile_image_path.split('\\')[-1] if '\\' in profile_image_path else profile_image_path
                    
                    if user_sid and not check_exists(cursor, 'UserProfiles', ['user_sid'], (user_sid,)):
                        cursor.execute('''INSERT INTO UserProfiles
                            (user_sid, username, profile_path, profile_image_path, profile_loaded, parsed_at)
                            VALUES (?, ?, ?, ?, ?, ?)''',
                            (user_sid, username, str(profile_image_path), str(profile_image_path),
                             int(profile_loaded), get_current_forensic_timestamp()))
                
                except Exception as e:
                    logging.error(f"Error with user profile {user_sid}: {e}")
        
        except Exception as e:
            logging.debug(f"ProfileList path unavailable: {e}")
        
        conn.commit()
        print("[OK] Computer name and timezone collected\n")
    except Exception as e:
        logging.error(f"Error with system info: {e}")

    # PHASE 7: WINDOWS UPDATE & SHUTDOWN (NEW)
    print("[SYSTEM] Collecting Windows Update and shutdown information...")
    try:
        # Windows Update
        try:
            winupdate_path = "Microsoft\\Windows\\CurrentVersion\\WindowsUpdate\\Auto Update"
            winupdate_values = read_registry_values(Software_reg_hive, winupdate_path)

            last_check_time = winupdate_values.get('LastCheckTime', ('', 'REG_SZ'))[0] if 'LastCheckTime' in winupdate_values else ''
            last_install_time = winupdate_values.get('LastInstallTime', ('', 'REG_SZ'))[0] if 'LastInstallTime' in winupdate_values else ''
            # Absent AUOptions is not 'Not configured' - it is nothing read.
            # Defaulting to 1 asserted a policy the hive does not state, and
            # disagreed with the live parser, which defaults to 0.
            au_options = winupdate_values.get('AUOptions', (0, 'REG_DWORD'))[0] if 'AUOptions' in winupdate_values else 0

            scheduled_install_day = winupdate_values.get('ScheduledInstallDay', (0, 'REG_DWORD'))[0] if 'ScheduledInstallDay' in winupdate_values else 0
            scheduled_install_time = winupdate_values.get('ScheduledInstallTime', (0, 'REG_DWORD'))[0] if 'ScheduledInstallTime' in winupdate_values else 0

            # parsed_at is the parse time and nothing else. A JSON fragment
            # naming the AUOptions meaning was appended to it, which put text
            # after the timestamp in the one column every table uses for
            # bookkeeping - so it no longer sorted or compared as a time. The
            # content audit could not see this: parsed_at is excluded from it
            # as provenance, by design.
            ts = get_current_forensic_timestamp()
            if not check_exists(cursor, 'WindowsUpdateInfo', ['last_check_time'], (str(last_check_time),)):
                cursor.execute('''INSERT OR IGNORE INTO WindowsUpdateInfo
                    (last_check_time, last_install_time, au_options, scheduled_install_day, scheduled_install_time, parsed_at)
                    VALUES (?, ?, ?, ?, ?, ?)''',
                    (str(last_check_time), str(last_install_time), int(au_options),
                     int(scheduled_install_day), int(scheduled_install_time), ts))

            # Raw layer. The live parser reads the WindowsUpdate key itself, not
            # its "Auto Update" child, so read the same key here - pointing this
            # at winupdate_values produced an empty table.
            _wu_root = "Microsoft\\Windows\\CurrentVersion\\WindowsUpdate"
            for _vn, _vt in (read_registry_values(Software_reg_hive, _wu_root) or {}).items():
                try:
                    _d, _t = _vt if isinstance(_vt, tuple) else (_vt, '')
                    if not check_exists(cursor, 'Windows_lastupdate',
                                        ['name'], (str(_vn),)):
                        cursor.execute(
                            'INSERT INTO Windows_lastupdate '
                            '(name, row_data, type) VALUES (?, ?, ?)',
                            (str(_vn), str(_d), str(_t)))
                    # SusClientIdValidation is a binary blob, and the decoded
                    # form is the only readable version of it. The live parser
                    # writes this derived row; this one stored the raw bytes and
                    # stopped, so the same evidence was legible in one parser
                    # and not the other.
                    if (str(_vn).lower() == "susclientidvalidation"
                            and isinstance(_d, bytes)):
                        _parsed = registry_binary_parser.parse_susclientid_validation(_d)
                        if _parsed and not check_exists(
                                cursor, 'Windows_lastupdate', ['name'],
                                ("SusClientIdValidation_Parsed",)):
                            cursor.execute(
                                'INSERT INTO Windows_lastupdate '
                                '(name, row_data, type) VALUES (?, ?, ?)',
                                ("SusClientIdValidation_Parsed", _parsed, "REG_SZ"))
                except Exception as e:
                    logging.debug(f"raw Windows_lastupdate {_vn}: {e}")

            # And its subkeys.
            for _sk in (get_subkeys(Software_reg_hive, _wu_root) or []):
                try:
                    for _vn, _vt in (read_registry_values(
                            Software_reg_hive, f"{_wu_root}\\{_sk}") or {}).items():
                        _d, _t = _vt if isinstance(_vt, tuple) else (_vt, '')
                        if not check_exists(cursor, 'Windows_lastupdate_subkeys',
                                            ['subkey', 'name'],
                                            (str(_sk), str(_vn))):
                            cursor.execute(
                                'INSERT INTO Windows_lastupdate_subkeys '
                                '(subkey, name, row_data, row_decoded, type) '
                                'VALUES (?, ?, ?, ?, ?)',
                                (str(_sk), str(_vn), str(_d),
                                 _off_decoded('Windows_lastupdate_subkeys',
                                              _vn, _d, _t), str(_t)))
                except Exception as e:
                    logging.debug(f"raw Windows_lastupdate_subkeys {_sk}: {e}")

            # A SuspiciousIndicators verdict was written here when
            # au_options == 2. The value itself is stored above in
            # WindowsUpdateInfo, where its meaning can be judged in context.

        except Exception as e:
            logging.debug(f"Windows Update path unavailable: {e}")

        # Shutdown Information
        try:
            # Use multi-path reader with ControlSet resolution
            shutdown_values, successful_paths = read_registry_multi_path(
                system_reg_hive,
                "Control\\Windows",
                controlset_dependent=True,
                active_controlset=active_controlset
            )
            
            if successful_paths:
                logging.debug(f"Extracted Shutdown info from {len(successful_paths)} path(s): {successful_paths}")

            shutdown_time_value = shutdown_values.get('ShutdownTime', ('', 'REG_BINARY'))[0] if 'ShutdownTime' in shutdown_values else ''
            # ShutdownTime is FILETIME
            shutdown_time = ''
            if shutdown_time_value and isinstance(shutdown_time_value, bytes) and len(shutdown_time_value) == 8:
                try:
                    logging.debug("Using registry_binary_parser.parse_filetime() for ShutdownTime")
                    shutdown_time = registry_binary_parser.parse_filetime(shutdown_time_value)
                except Exception as e:
                    logging.error(f"Error parsing ShutdownTime: {e}")

            # The rest of the key. Only shutdown_time was written, so three
            # columns were NULL offline and 0 live for the same evidence - and
            # ShutdownCount is a real value in this key that nothing was reading.
            def _sd_int(vname):
                _v = shutdown_values.get(vname)
                if isinstance(_v, tuple):
                    _v = _v[0]
                try:
                    return int(_v)
                except (TypeError, ValueError):
                    return 0

            shutdown_count = _sd_int('ShutdownCount')
            clean_shutdown = _sd_int('CleanShutdown')
            _sd_type = shutdown_values.get('ShutdownType', ('', ''))
            shutdown_type = str(_sd_type[0] if isinstance(_sd_type, tuple) else _sd_type)

            if not check_exists(cursor, 'ShutdownInfo', ['shutdown_time'], (shutdown_time,)):
                cursor.execute('''INSERT OR IGNORE INTO ShutdownInfo
                    (shutdown_time, shutdown_count, shutdown_type, clean_shutdown, parsed_at)
                    VALUES (?, ?, ?, ?, ?)''',
                    (shutdown_time, shutdown_count, shutdown_type, clean_shutdown,
                     get_current_forensic_timestamp()))

            # Raw layer for the same key.
            for _vn, _vt in (shutdown_values or {}).items():
                try:
                    _d, _t = _vt if isinstance(_vt, tuple) else (_vt, '')
                    if not check_exists(cursor, 'shutdown_information',
                                        ['name'], (str(_vn),)):
                        cursor.execute(
                            'INSERT INTO shutdown_information '
                            '(name, row_data, row_decoded, type) '
                            'VALUES (?, ?, ?, ?)',
                            (str(_vn), str(_d),
                             _off_decoded('shutdown_information', _vn, _d, _t),
                             str(_t)))
                except Exception as e:
                    logging.debug(f"raw shutdown_information {_vn}: {e}")

        except Exception as e:
            logging.debug(f"Shutdown info unavailable: {e}")

        conn.commit()
        print("[OK] System information collected\n")
    except Exception as e:
        logging.error(f"Error with system info: {e}")

    # ========================================================================
    # SCHEDULED TASKS (TaskCache)  -  SOFTWARE hive
    #
    # SOFTWARE\Microsoft\Windows NT\CurrentVersion\Schedule\TaskCache.
    # NOT SYSTEM\CurrentControlSet\Services\Schedule: that key exists but holds
    # no TaskCache, so aiming there returns nothing at all rather than failing.
    # Tree maps a human task path to the {GUID} under Tasks; Plain/Logon/Boot/
    # Maintenance index the same GUIDs by trigger type, which is a persistence
    # signal without decoding the Triggers blob.
    # ========================================================================
    try:
        cursor.execute("""
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
        )""")

        if not Software_reg_hive:
            print("Scheduled Tasks: SOFTWARE hive not available - skipped")
        else:
            _tc_base = "Microsoft\\Windows NT\\CurrentVersion\\Schedule\\TaskCache"
            _tc_reg = Registry.Registry(Software_reg_hive)

            def _tc_open(subpath):
                try:
                    return _tc_reg.open(_tc_base + "\\" + subpath)
                except Exception:
                    return None

            # {GUID} -> human task path
            _tc_tree = {}

            def _tc_walk(key, prefix):
                for child in key.subkeys():
                    path = prefix + "\\" + child.name()
                    try:
                        guid = child.value("Id").value()
                        _tc_tree[str(guid).upper()] = path
                    except Exception:
                        pass  # a folder, not a task
                    _tc_walk(child, path)

            _tree_key = _tc_open("Tree")
            if _tree_key is not None:
                _tc_walk(_tree_key, "")

            # {GUID} -> trigger buckets it appears in
            _tc_triggers = {}
            for _bucket in ("Plain", "Logon", "Boot", "Maintenance"):
                _bk = _tc_open(_bucket)
                if _bk is None:
                    continue
                for _sk in _bk.subkeys():
                    _tc_triggers.setdefault(_sk.name().upper(), []).append(_bucket)

            _tasks_key = _tc_open("Tasks")
            _task_count = 0
            if _tasks_key is None:
                print("Scheduled Tasks: TaskCache\\Tasks not present in this SOFTWARE hive")
            else:
                for _tk in _tasks_key.subkeys():
                    guid_u = _tk.name().upper()

                    def _tc_val(name):
                        try:
                            return _tk.value(name).value()
                        except Exception:
                            return None

                    task_path = _tc_tree.get(guid_u) or _tc_val("Path") or guid_u

                    dyn = {}
                    _di = _tc_val("DynamicInfo")
                    if isinstance(_di, bytes):
                        dyn = registry_binary_parser.parse_taskcache_dynamic_info(_di)

                    acts = {}
                    _ac = _tc_val("Actions")
                    if isinstance(_ac, bytes):
                        acts = registry_binary_parser.parse_taskcache_actions(_ac)

                    first = (acts.get("actions") or [{}])[0]
                    command = first.get("command", "")
                    arguments = first.get("arguments", "")
                    stamp = format_forensic_timestamp(get_current_utc())

                    cursor.execute(
                        """INSERT OR REPLACE INTO ScheduledTasks
                           (task_path, task_guid, command, arguments, working_dir,
                            run_context, triggers_index, task_registered, last_run,
                            last_completed, last_result, parsed_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (task_path, guid_u, command, arguments,
                         first.get("working_dir", ""), acts.get("context", ""),
                         ",".join(_tc_triggers.get(guid_u, [])),
                         dyn.get("task_registered"), dyn.get("last_run"),
                         dyn.get("last_completed"), dyn.get("last_result"), stamp))

                    # Reuse: a scheduled task IS an autostart entry, so it goes in
                    # the same table the Run keys use rather than a parallel one.
                    if command:
                        full = (command + " " + arguments).strip() if arguments else command
                        try:
                            cursor.execute(
                                """INSERT OR IGNORE INTO AutoStartPrograms
                                   (location, program_name, command, record_state, parsed_at)
                                   VALUES (?, ?, ?, ?, ?)""",
                                ("TaskCache" + task_path,
                                 task_path.rsplit("\\", 1)[-1], full, LIVE_STATE,
                                 stamp))
                        except Exception:
                            pass  # AutoStartPrograms may not exist in every schema
                    _task_count += 1

                conn.commit()
                print(f"Scheduled Tasks collected successfully. Total tasks: {_task_count}")

    except Exception as e:
        logging.error(f"Error collecting Scheduled Tasks (offline): {e}")
        print(f"Warning: Could not collect Scheduled Tasks data: {e}")

    # ========================================================================
    # PHASE: Persistence keys (ASEP)
    #
    # Mirrors the live parser's persistence section exactly - same tables, same
    # columns, same AutoStartPrograms roll-up locations. The live schema is the
    # reference; a case parsed from an image must yield the same tables as the
    # same machine parsed live.
    #
    # Paths are hive-relative here: the SOFTWARE hive file IS "SOFTWARE", so the
    # live path SOFTWARE\Microsoft\... becomes Microsoft\... , and SYSTEM paths
    # resolve through the active ControlSet rather than CurrentControlSet.
    # ========================================================================
    print("\n[PERSISTENCE] Collecting ASEP / persistence keys...")
    try:
        for _t in ("winlogon", "image_file_execution_options", "appinit_dlls",
                   "appcert_dlls", "active_setup", "run_services",
                   "run_services_once", "policies_explorer_run",
                   "user_shell_folders", "lsa_packages", "boot_execute",
                   "clsid_inprocserver32",
                   # Named for the artifact, not the technique - matches live.
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
            # Additive migration, matching the live parser: a case
            # from an earlier build has no data_decoded, and
            # CREATE TABLE IF NOT EXISTS is a no-op on it.
            cursor.execute(f'PRAGMA table_info({_t})')
            if 'data_decoded' not in [c[1] for c in cursor.fetchall()]:
                try:
                    cursor.execute(
                        f'ALTER TABLE {_t} ADD COLUMN data_decoded TEXT')
                except sqlite3.Error as _mig:
                    logging.debug('data_decoded migration %s: %s', _t, _mig)

        _asep_cs = get_active_controlset(system_reg_hive) if system_reg_hive else "ControlSet001"
        _asep_stamp = format_forensic_timestamp(get_current_utc())
        _asep_count = 0

        def _asep_fmt(data):
            # REG_MULTI_SZ arrives as a list; join rather than store a repr, so
            # the column matches what the live parser writes.
            #
            # Trailing empties are the NUL terminator, not data. python-registry
            # keeps them where winreg drops them, which made every REG_MULTI_SZ
            # value differ between the two parsers.
            if isinstance(data, list):
                items = [str(x) for x in data]
                while items and items[-1] == "":
                    items.pop()
                return "; ".join(items)
            return str(data)

        def _asep_record(table, hive_label, key_path, name, data, rtype,
                         user_name=None, roll_up=None):
            nonlocal _asep_count
            value = _asep_fmt(data)
            # Guarded, like the rest of the parser: these tables carry no
            # constraint and nothing clears them, so an unguarded INSERT
            # duplicates the whole artifact on every re-parse.
            if not check_exists(cursor, table, ['hive', 'key_path', 'name'],
                                (hive_label, key_path, name)):
                # A machine-wide key has no user to attribute, and a blank cell
                # reads as attribution having failed. Label it instead, matching
                # the live parser so the two agree row for row.
                _owner = user_name or user_identity.MACHINE_WIDE_LABEL
                # The same decoder the live parser uses, so the two
                # agree on this column as they do on every other.
                _dec = registry_binary_parser.render_registry_value(
                    table, name, data, rtype, _asep_env)
                if _dec == value:
                    _dec = ''              # a copy is not a decode
                cursor.execute(
                    f'INSERT INTO {table} (hive, key_path, name, data, '
                    'data_decoded, type, user_name, parsed_at) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                    (hive_label, key_path, name, value, _dec, rtype,
                     _owner, _asep_stamp))
                _asep_count += 1
            if roll_up and value:
                loc = roll_up if not user_name else f"HKU\\{user_name} {roll_up}"
                if not check_exists(cursor, 'AutoStartPrograms',
                                    ['location', 'program_name'], (loc, name)):
                    cursor.execute(
                        'INSERT INTO AutoStartPrograms '
                        '(location, program_name, command, key_path, '
                        'record_state, parsed_at) '
                        'VALUES (?, ?, ?, ?, ?, ?)',
                        (loc, name, value, key_path, LIVE_STATE, _asep_stamp))

        def _asep_vals(hive_file, key, names=None):
            """(name, data, type) tuples; [] when the key or hive is absent.

            Name matching is case-INSENSITIVE, because the registry is and
            winreg therefore is too. python-registry reports the stored casing
            verbatim, so an exact comparison here silently drops any value
            whose casing differs from the literal in the caller's list - the
            Winlogon key really does store "VMApplet" while every parser and
            reference writes "VmApplet", so that ASEP appeared live and
            vanished offline with no error on either side.
            """
            if not hive_file:
                return []
            vals = read_registry_values(hive_file, key)
            if not vals:
                return []
            wanted = {str(x).lower() for x in names} if names else None
            out = []
            for n, (d, t) in vals.items():
                nm = _default_name(n)
                if wanted is not None and str(nm).lower() not in wanted:
                    continue
                out.append((nm, d, t))
            return out

        # The expansion environment, read from the IMAGE's own SOFTWARE
        # hive - never os.environ. A machine installed to D:\Windows must
        # not be reported with the examiner's C:\Windows, and an image is
        # always somebody else's computer. No hive means no expansion,
        # which is the right answer rather than a plausible wrong one.
        _asep_env = {}
        try:
            for _n, _d, _t2 in (_asep_vals(
                    Software_reg_hive,
                    r'Microsoft\Windows NT\CurrentVersion',
                    ['SystemRoot', 'ProgramFilesDir', 'CommonFilesDir']) or []):
                if _d:
                    _asep_env[str(_n)] = str(_d)
            if 'SystemRoot' in _asep_env:
                _asep_env.setdefault('windir', _asep_env['SystemRoot'])
        except Exception as _env_exc:
            logging.debug('offline evidence environment: %s', _env_exc)

        SW = Software_reg_hive
        SY = system_reg_hive

        # 1. Winlogon
        _WL = r"Microsoft\Windows NT\CurrentVersion\Winlogon"
        for nm, dt, ty in _asep_vals(SW, _WL,
                ["Shell", "Userinit", "Taskman", "AppSetup", "VmApplet", "GinaDLL",
                 "System", "AutoAdminLogon", "DefaultUserName"]):
            _asep_record("winlogon", "HKLM", "SOFTWARE\\" + _WL, nm, dt, ty,
                         roll_up="HKLM Winlogon" if nm in ("Shell", "Userinit", "Taskman",
                                                           "GinaDLL", "AppSetup") else None)
        for sub in (get_subkeys(SW, _WL + r"\Notify") or [] if SW else []):
            for nm, dt, ty in _asep_vals(SW, f"{_WL}\\Notify\\{sub}",
                                         ["DllName", "Logon", "Startup"]):
                _asep_record("winlogon", "HKLM", f"SOFTWARE\\{_WL}\\Notify\\{sub}",
                             nm, dt, ty,
                             roll_up="HKLM Winlogon\\Notify" if nm == "DllName" else None)

        # 2. IFEO - only entries that redirect or monitor execution.
        _IFEO = r"Microsoft\Windows NT\CurrentVersion\Image File Execution Options"
        for sub in (get_subkeys(SW, _IFEO) or [] if SW else []):
            if str(sub).lower() == "silentprocessexit":
                continue
            for nm, dt, ty in _asep_vals(SW, f"{_IFEO}\\{sub}",
                                         ["Debugger", "GlobalFlag", "VerifierDlls"]):
                _asep_record("image_file_execution_options", "HKLM",
                             f"SOFTWARE\\{_IFEO}\\{sub}", f"{sub}!{nm}", dt, ty,
                             roll_up="HKLM IFEO\\Debugger" if nm == "Debugger" else None)
        for sub in (get_subkeys(SW, _IFEO + r"\SilentProcessExit") or [] if SW else []):
            for nm, dt, ty in _asep_vals(SW, f"{_IFEO}\\SilentProcessExit\\{sub}",
                                         ["MonitorProcess", "ReportingMode"]):
                _asep_record("image_file_execution_options", "HKLM",
                             f"SOFTWARE\\{_IFEO}\\SilentProcessExit\\{sub}",
                             f"{sub}!{nm}", dt, ty,
                             roll_up="HKLM SilentProcessExit" if nm == "MonitorProcess" else None)

        # 3. AppInit_DLLs
        for label, p in (("HKLM", r"Microsoft\Windows NT\CurrentVersion\Windows"),
                         ("HKLM32", r"WOW6432Node\Microsoft\Windows NT\CurrentVersion\Windows")):
            for nm, dt, ty in _asep_vals(SW, p,
                    ["AppInit_DLLs", "LoadAppInit_DLLs", "RequireSignedAppInit_DLLs"]):
                _asep_record("appinit_dlls", label, "SOFTWARE\\" + p, nm, dt, ty,
                             roll_up=f"{label} AppInit_DLLs" if nm == "AppInit_DLLs" else None)

        # 4. AppCertDlls (SYSTEM hive, ControlSet-relative)
        _ACD = f"{_asep_cs}\\Control\\Session Manager\\AppCertDlls"
        for nm, dt, ty in _asep_vals(SY, _ACD):
            _asep_record("appcert_dlls", "HKLM", "SYSTEM\\" + _ACD, nm, dt, ty,
                         roll_up="HKLM AppCertDlls")

        # 5. Active Setup
        for label, base in (("HKLM", r"Microsoft\Active Setup\Installed Components"),
                            ("HKLM32", r"WOW6432Node\Microsoft\Active Setup\Installed Components")):
            for comp in (get_subkeys(SW, base) or [] if SW else []):
                for nm, dt, ty in _asep_vals(SW, f"{base}\\{comp}",
                                             ["StubPath", "Version", "IsInstalled"]):
                    _asep_record("active_setup", label, f"SOFTWARE\\{base}\\{comp}",
                                 f"{comp}!{nm}", dt, ty,
                                 roll_up=f"{label} Active Setup" if nm == "StubPath" else None)

        # 6/7/8. Legacy and policy autostart locations
        for table, key, roll in (
                ("run_services", r"Microsoft\Windows\CurrentVersion\RunServices", "RunServices"),
                ("run_services_once", r"Microsoft\Windows\CurrentVersion\RunServicesOnce", "RunServicesOnce"),
                ("policies_explorer_run", r"Microsoft\Windows\CurrentVersion\Policies\Explorer\Run", "Policies\\Explorer\\Run")):
            for nm, dt, ty in _asep_vals(SW, key):
                _asep_record(table, "HKLM", "SOFTWARE\\" + key, nm, dt, ty,
                             roll_up=f"HKLM {roll}")

        _USF = r"Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        for nm, dt, ty in _asep_vals(SW, _USF, ["Common Startup", "Startup"]):
            _asep_record("user_shell_folders", "HKLM", "SOFTWARE\\" + _USF, nm, dt, ty,
                         roll_up="HKLM User Shell Folders")

        # 9. LSA packages
        _LSA = f"{_asep_cs}\\Control\\Lsa"
        for nm, dt, ty in _asep_vals(SY, _LSA,
                ["Notification Packages", "Security Packages", "Authentication Packages"]):
            _asep_record("lsa_packages", "HKLM", "SYSTEM\\" + _LSA, nm, dt, ty,
                         roll_up="HKLM Lsa")

        # 10. Session Manager execute lists
        _SM = f"{_asep_cs}\\Control\\Session Manager"
        for nm, dt, ty in _asep_vals(SY, _SM,
                ["BootExecute", "SetupExecute", "Execute", "S0InitialCommand"]):
            _asep_record("boot_execute", "HKLM", "SYSTEM\\" + _SM, nm, dt, ty,
                         roll_up="HKLM Session Manager")

        # 10b. Per-user autostart locations, one pass per NTUSER hive.
        #
        # The live parser gained this and the offline one did not, so
        # user_shell_folders held 27 rows live and 1 offline from the same
        # machine - the HKCU copy is the Startup-folder redirect, and offline
        # could not see it at all. Caught by comparing the two parsers over one
        # exported hive set, which is the only way a divergence like this
        # surfaces: each parser looks correct on its own.
        for _nt in (ntuser_hives or []):
            if not _nt or not os.path.exists(_nt):
                continue
            _nt_user = user_identity.display_owner(_nt, _identity_accounts)
            try:
                _u_usf = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
                for nm, dt, ty in _asep_vals(_nt, _u_usf):
                    _asep_record("user_shell_folders", "HKCU", _u_usf, nm, dt, ty,
                                 user_name=_nt_user, roll_up="User Shell Folders")

                _u_as = r"Software\Microsoft\Active Setup\Installed Components"
                for _comp in (get_subkeys(_nt, _u_as) or []):
                    _kp = _u_as + "\\" + _comp
                    for nm, dt, ty in _asep_vals(
                            _nt, _kp, ["StubPath", "Version", "IsInstalled"]):
                        _asep_record("active_setup", "HKCU", _kp, nm, dt, ty,
                                     user_name=_nt_user, roll_up="Active Setup")

                _u_per = r"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer\Run"
                for nm, dt, ty in _asep_vals(_nt, _u_per):
                    _asep_record("policies_explorer_run", "HKCU", _u_per, nm, dt, ty,
                                 user_name=_nt_user, roll_up="Policies Explorer Run")

                _u_cp = r"Software\Microsoft\Command Processor"
                for nm, dt, ty in _asep_vals(_nt, _u_cp, ["AutoRun"]):
                    _asep_record("command_processor", "HKCU", _u_cp, nm, dt, ty,
                                 user_name=_nt_user, roll_up="Command Processor")
            except Exception as _e:
                logging.debug("per-user ASEP pass failed for %s: %s", _nt, _e)

        # 11. COM hijacking - per-user CLSID shadowing the machine-wide one.
        # Offline this is per UsrClass.dat hive, one per user.
        for _uc in (usrclass_hives or []):
            # display_owner resolves a UsrClass hive by the SID it carries and
            # returns MACHINE\username - the form every other user_name in this
            # database uses. Deriving the name from the file's own path instead
            # produced a bare "Ghass", so this one roll-up landed under
            # "HKU\Ghass COM InprocServer32" while the rest of the same user's
            # rows sat under "HKU\CROW-PC\Ghass ...". Same user, two labels.
            _uname = user_identity.display_owner(_uc, _identity_accounts)
            for clsid in (get_subkeys(_uc, "CLSID") or []):
                uv = _asep_vals(_uc, f"CLSID\\{clsid}\\InprocServer32")
                if not uv:
                    continue
                if not _asep_vals(SW, rf"Classes\CLSID\{clsid}\InprocServer32"):
                    continue                     # nothing machine-wide to shadow
                for nm, dt, ty in uv:
                    _asep_record("clsid_inprocserver32", "HKCU",
                                 f"UsrClass\\CLSID\\{clsid}\\InprocServer32",
                                 f"{clsid}!{nm}", dt, ty, user_name=_uname,
                                 roll_up="COM InprocServer32" if nm == "(Default)" else None)

        def _asep_clsid_dll(clsid):
            """Server path behind a CLSID, or "" - mirrors the live helper.

            Ask for the default value by name. Taking the first enumerated value
            instead yields ThreadingModel ("Apartment") rather than a path on
            most InprocServer32 keys - a plausible value, not an error.

            Per-user installs register only in UsrClass, so those hives are
            searched too.

            The 32-bit view is "Classes\\Wow6432Node\\CLSID" on disk.
            "WOW6432Node\\Classes\\CLSID" is what winreg shows live, but that is
            a redirection alias the hive file does not contain - using the live
            spelling here resolves nothing and leaves the column quietly blank
            while the row count still matches.
            """
            for _h, _b in ([(SW, r"Classes\CLSID"),
                            (SW, r"Classes\Wow6432Node\CLSID"),
                            (SW, r"WOW6432Node\Classes\CLSID")]
                           + [(_u, "CLSID") for _u in (usrclass_hives or [])]):
                if not _h:
                    continue
                for _srv in ("InprocServer32", "LocalServer32"):
                    for _n, _d, _t in _asep_vals(_h, rf"{_b}\{clsid}\{_srv}",
                                                 ["(Default)"]):
                        if _d:
                            return _asep_fmt(_d)
            return ""

        # 12. Command Processor AutoRun - runs on every cmd.exe launch.
        _CP = r"Microsoft\Command Processor"
        for nm, dt, ty in _asep_vals(SW, _CP,
                ["AutoRun", "DefaultColor", "CompletionChar"]):
            _asep_record("command_processor", "HKLM", "SOFTWARE\\" + _CP, nm, dt, ty,
                         roll_up="HKLM Command Processor" if nm == "AutoRun" else None)
        # NTUSER hives carry their own "Software" level - the SOFTWARE hive file
        # IS that level, so the same artifact needs a different prefix here.
        _CP_U = "Software\\" + _CP
        for _nt in (ntuser_hives or []):
            _un = user_identity.display_owner(_nt, _identity_accounts) \
                if hasattr(user_identity, "display_owner") else None
            for nm, dt, ty in _asep_vals(_nt, _CP_U,
                    ["AutoRun", "DefaultColor", "CompletionChar"]):
                _asep_record("command_processor", "HKCU", "NTUSER\\" + _CP_U,
                             nm, dt, ty, user_name=_un,
                             roll_up="HKCU Command Processor" if nm == "AutoRun" else None)

        # 13. Drivers32 - multimedia driver DLLs loaded by winmm.
        for _hv, _p in (("HKLM", r"Microsoft\Windows NT\CurrentVersion\Drivers32"),
                        ("HKLM32", r"WOW6432Node\Microsoft\Windows NT"
                                   r"\CurrentVersion\Drivers32")):
            for nm, dt, ty in _asep_vals(SW, _p):
                _asep_record("drivers32", _hv, "SOFTWARE\\" + _p, nm, dt, ty,
                             roll_up=f"{_hv} Drivers32")

        # 14. ShellServiceObjectDelayLoad - COM objects Explorer loads at startup.
        _SSODL = r"Microsoft\Windows\CurrentVersion\ShellServiceObjectDelayLoad"
        for nm, dt, ty in _asep_vals(SW, _SSODL):
            _asep_record("shell_service_object_delay_load", "HKLM",
                         "SOFTWARE\\" + _SSODL, nm, dt, ty, roll_up="HKLM SSODL")

        # 15. Browser Helper Objects - resolve the CLSID to the backing DLL.
        for _hv, _bho in (("HKLM", r"Microsoft\Windows\CurrentVersion"
                                   r"\Explorer\Browser Helper Objects"),
                          ("HKLM32", r"WOW6432Node\Microsoft\Windows"
                                     r"\CurrentVersion\Explorer\Browser Helper Objects")):
            for clsid in (get_subkeys(SW, _bho) or [] if SW else []):
                _asep_record("browser_helper_objects", _hv,
                             f"SOFTWARE\\{_bho}\\{clsid}", clsid,
                             _asep_clsid_dll(clsid), "REG_SZ",
                             roll_up=f"{_hv} Browser Helper Objects")

        # 16. SharedTaskScheduler - absent on modern Windows; presence is signal.
        _STS = r"Microsoft\Windows\CurrentVersion\Explorer\SharedTaskScheduler"
        for nm, dt, ty in _asep_vals(SW, _STS):
            _asep_record("shared_task_scheduler", "HKLM", "SOFTWARE\\" + _STS,
                         nm, dt, ty, roll_up="HKLM SharedTaskScheduler")

        # 17. Shell icon overlay handlers - in-process DLLs loaded by Explorer.
        _SIOI = (r"Microsoft\Windows\CurrentVersion\Explorer"
                 r"\ShellIconOverlayIdentifiers")
        for sub in (get_subkeys(SW, _SIOI) or [] if SW else []):
            for nm, dt, ty in _asep_vals(SW, f"{_SIOI}\\{sub}", ["(Default)"]):
                _c = _asep_fmt(dt)
                _d = _asep_clsid_dll(_c)
                _asep_record("shell_icon_overlay_identifiers", "HKLM",
                             f"SOFTWARE\\{_SIOI}\\{sub}", sub,
                             f"{_c} -> {_d}" if _d else _c, ty,
                             roll_up="HKLM ShellIconOverlayIdentifiers")

        # 18. Credential providers - DLLs in the logon UI.
        for _lbl, _cpk in (
                ("Credential Providers",
                 r"Microsoft\Windows\CurrentVersion\Authentication"
                 r"\Credential Providers"),
                ("Credential Provider Filters",
                 r"Microsoft\Windows\CurrentVersion\Authentication"
                 r"\Credential Provider Filters")):
            for clsid in (get_subkeys(SW, _cpk) or [] if SW else []):
                _d = _asep_clsid_dll(clsid)
                _nm = _asep_vals(SW, f"{_cpk}\\{clsid}", ["(Default)"])
                _asep_record("credential_providers", "HKLM",
                             f"SOFTWARE\\{_cpk}\\{clsid}", f"{_lbl}!{clsid}",
                             "%s [%s]" % (_asep_fmt(_nm[0][1]) if _nm else "",
                                          _d or "no registered server"),
                             "REG_SZ", roll_up="HKLM Credential Providers")

        # 19. Netsh helper DLLs - loaded every time netsh.exe runs.
        _NETSH = r"Microsoft\Netsh"
        for nm, dt, ty in _asep_vals(SW, _NETSH):
            _asep_record("netsh_helper_dlls", "HKLM", "SOFTWARE\\" + _NETSH,
                         nm, dt, ty, roll_up="HKLM Netsh")

        # 20. AMSI providers - a hostile provider sees every script AMSI scans.
        _AMSI = r"Microsoft\AMSI\Providers"
        for clsid in (get_subkeys(SW, _AMSI) or [] if SW else []):
            _asep_record("amsi_providers", "HKLM", f"SOFTWARE\\{_AMSI}\\{clsid}",
                         clsid, _asep_clsid_dll(clsid), "REG_SZ",
                         roll_up="HKLM AMSI Providers")

        # 21. Security Support Providers - DLLs loaded into lsass at boot.
        _SSP = f"{_asep_cs}\\Control\\SecurityProviders"
        for nm, dt, ty in _asep_vals(SY, _SSP, ["SecurityProviders"]):
            _asep_record("security_providers", "HKLM", "SYSTEM\\" + _SSP, nm, dt, ty,
                         roll_up="HKLM SecurityProviders")

        # 22. Print monitors - DLLs loaded by spoolsv.exe as SYSTEM.
        _PMON = f"{_asep_cs}\\Control\\Print\\Monitors"
        for sub in (get_subkeys(SY, _PMON) or [] if SY else []):
            for nm, dt, ty in _asep_vals(SY, f"{_PMON}\\{sub}", ["Driver"]):
                _asep_record("print_monitors", "HKLM", f"SYSTEM\\{_PMON}\\{sub}",
                             f"{sub}!{nm}", dt, ty, roll_up="HKLM Print Monitors")

        # 23. Print processors - same spooler load point, one level deeper.
        _PENV = f"{_asep_cs}\\Control\\Print\\Environments"
        for env in (get_subkeys(SY, _PENV) or [] if SY else []):
            _pp = f"{_PENV}\\{env}\\Print Processors"
            for proc in (get_subkeys(SY, _pp) or [] if SY else []):
                for nm, dt, ty in _asep_vals(SY, f"{_pp}\\{proc}", ["Driver"]):
                    _asep_record("print_processors", "HKLM", f"SYSTEM\\{_pp}\\{proc}",
                                 f"{env}\\{proc}!{nm}", dt, ty,
                                 roll_up="HKLM Print Processors")

        # 24. Network providers - ProviderOrder plus each provider's DLL.
        _NPO = f"{_asep_cs}\\Control\\NetworkProvider\\Order"
        for nm, dt, ty in _asep_vals(SY, _NPO, ["ProviderOrder"]):
            _asep_record("network_providers", "HKLM", "SYSTEM\\" + _NPO, nm, dt, ty,
                         roll_up="HKLM NetworkProvider Order")
            for _svc in _asep_fmt(dt).split(","):
                _svc = _svc.strip()
                if not _svc:
                    continue
                _pp = f"{_asep_cs}\\Services\\{_svc}\\NetworkProvider"
                for _n2, _d2, _t2 in _asep_vals(SY, _pp, ["ProviderPath", "Name"]):
                    _asep_record("network_providers", "HKLM", "SYSTEM\\" + _pp,
                                 f"{_svc}!{_n2}", _d2, _t2)

        # 25. WMI autorecover MOFs - recompiled when the repository rebuilds.
        _CIMOM = r"Microsoft\WBEM\CIMOM"
        for nm, dt, ty in _asep_vals(SW, _CIMOM,
                ["Autorecover MOFs", "Autorecover MOFs timestamp"]):
            _asep_record("wmi_autorecover_mofs", "HKLM", "SOFTWARE\\" + _CIMOM,
                         nm, dt, ty,
                         roll_up="HKLM WMI Autorecover MOFs"
                                 if nm == "Autorecover MOFs" else None)

        # 26. Per-user Load and Run, from each NTUSER hive.
        _UWIN = r"Software\Microsoft\Windows NT\CurrentVersion\Windows"
        for _nt in (ntuser_hives or []):
            _un = user_identity.display_owner(_nt, _identity_accounts) \
                if hasattr(user_identity, "display_owner") else None
            for nm, dt, ty in _asep_vals(_nt, _UWIN, ["Load", "Run"]):
                _asep_record("windows_load_run", "HKCU", "NTUSER\\" + _UWIN,
                             nm, dt, ty, user_name=_un,
                             roll_up="HKCU Windows Load/Run")

        # 27. shell\open\command for the ProgIDs used by the known UAC bypasses.
        # A per-user entry overrides the machine-wide handler. Recorded as the
        # artifact it is; DelegateExecute is included because the fodhelper
        # technique works by adding (Default) and blanking it.
        _PROGIDS = ("exefile", "ms-settings", "mscfile", "Folder", "txtfile",
                    "batfile", "cmdfile", "regfile")
        for _progid in _PROGIDS:
            _soc = rf"Classes\{_progid}\shell\open\command"
            for nm, dt, ty in _asep_vals(SW, _soc):
                _asep_record("shell_open_command", "HKLM", "SOFTWARE\\" + _soc,
                             f"{_progid}!{nm}", dt, ty)
            for _uc in (usrclass_hives or []):
                _un = None
                try:
                    _p = os.path.normpath(_uc).split(os.sep)
                    if "AppData" in _p:
                        _un = _p[_p.index("AppData") - 1]
                except Exception:
                    _un = None
                _ucsoc = rf"{_progid}\shell\open\command"
                for nm, dt, ty in _asep_vals(_uc, _ucsoc):
                    _asep_record("shell_open_command", "HKCU",
                                 "UsrClass\\" + _ucsoc, f"{_progid}!{nm}", dt, ty,
                                 user_name=_un,
                                 roll_up="HKCU shell\\open\\command")

        conn.commit()
        print(f"[OK] Persistence keys collected successfully. Total values: {_asep_count}")

    except Exception as e:
        logging.error(f"Error collecting persistence keys (offline): {e}")
        print(f"Warning: Could not collect persistence key data: {e}")

    # ========================================================================
    # PHASE: Forensic coverage (security posture, exposure, devices, per-user)
    #
    # Mirrors the live parser's coverage section exactly - same tables, same
    # columns. Paths are hive-relative here and SYSTEM paths resolve through the
    # active ControlSet rather than CurrentControlSet.
    # ========================================================================
    print("\n[COVERAGE] Collecting security posture, exposure and device keys...")
    try:
        _cov_cs = get_active_controlset(system_reg_hive) if system_reg_hive else "ControlSet001"
        _cov_stamp = format_forensic_timestamp(get_current_utc())
        _cov_counts = {}

        for _sql in (
            '''CREATE TABLE IF NOT EXISTS SecurityPosture (
                setting TEXT, value_raw TEXT, value_decoded TEXT, default_value TEXT,
                assessment TEXT, meaning TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS DefenderExclusions (
                exclusion_type TEXT, value TEXT, source TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS FirewallRules (
                rule_type TEXT, rule_name TEXT, display_name TEXT, action TEXT,
                direction TEXT, enabled TEXT, protocol TEXT, local_port TEXT,
                remote_port TEXT, application TEXT, service TEXT, profile TEXT,
                key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS NetworkShares (
                share_name TEXT, share_path TEXT, remark TEXT, raw TEXT,
                key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS ConnectedDevices (
                device_type TEXT, device_id TEXT, friendly_name TEXT, details TEXT,
                key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS MountPoints2 (
                user_name TEXT, mount_id TEXT, mount_type TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS RDPClientMRU (
                user_name TEXT, entry_type TEXT, server TEXT, username_hint TEXT,
                key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS OfficeDocuments (
                user_name TEXT, application TEXT, version TEXT, kind TEXT,
                document TEXT, raw TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS FeatureUsage (
                user_name TEXT, usage_type TEXT, program TEXT, count INTEGER,
                key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS CompatibilityAssistant (
                user_name TEXT, program_path TEXT, blob_size INTEGER,
                key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS RecentApps (
                user_name TEXT, app_id TEXT, app_path TEXT, launch_count INTEGER,
                last_accessed TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS ApplicationArtifacts (
                user_name TEXT, application TEXT, artifact TEXT, name TEXT,
                value TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''',
            # Per-user activity - same shape as the live parser.
            '''CREATE TABLE IF NOT EXISTS file_exts (
                user_name TEXT, extension TEXT, choice_type TEXT, progid TEXT,
                key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS cid_size_mru (
                user_name TEXT, position INTEGER, application TEXT,
                key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS programs_cache (
                user_name TEXT, value_name TEXT, blob_size INTEGER,
                key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS regedit_lastkey (
                user_name TEXT, name TEXT, value TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT,
                parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS printer_connections (
                user_name TEXT, connection TEXT, server TEXT, printer TEXT,
                key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS explorer_advanced (
                user_name TEXT, setting TEXT, value TEXT, value_decoded TEXT, default_value TEXT,
                meaning TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''',
            # Posture - one table per artifact, each carrying its stock default.
            '''CREATE TABLE IF NOT EXISTS rdp_tcp (
                setting TEXT, value TEXT, value_decoded TEXT, default_value TEXT, meaning TEXT,
                key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS usbstor_start (
                setting TEXT, value TEXT, decoded TEXT, default_value TEXT,
                key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS windows_script_host (
                setting TEXT, value TEXT, value_decoded TEXT, default_value TEXT, meaning TEXT,
                key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS dnscache_parameters (
                name TEXT, value TEXT, value_decoded TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS files_not_to_snapshot (
                entry TEXT, value TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS winevt_channels (
                channel TEXT, source TEXT, enabled TEXT, max_size TEXT,
                retention TEXT, log_file TEXT, reason TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT,
                parsed_at TEXT)''',
            # Device attribution.
            '''CREATE TABLE IF NOT EXISTS wpdbusenum (
                device_id TEXT, friendly_name TEXT, volume_guid TEXT,
                key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS device_classes (
                class_guid TEXT, class_name TEXT, device_instance TEXT,
                key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS volume_info_cache (
                drive_letter TEXT, volume_label TEXT, file_system TEXT,
                key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''',
            # Host identity.
            '''CREATE TABLE IF NOT EXISTS machine_guid (
                name TEXT, value TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS product_options (
                name TEXT, value TEXT, meaning TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT,
                parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS os_install_history (
                name TEXT, value TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS active_computer_name (
                name TEXT, value TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS hivelist (
                hive TEXT, file_path TEXT, key_path TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS system_environment (
                name TEXT, value TEXT, value_decoded TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS network_adapters (
                adapter_guid TEXT, name TEXT, value TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT,
                parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS group_policy_history (
                scope TEXT, gpo_id TEXT, name TEXT, value TEXT, key_path TEXT,
        last_written TEXT, time_basis TEXT,
                parsed_at TEXT)'''):
            cursor.execute(_sql)

        def _cov_dec(table, name, data, vtype=None):

            """The decoded form of a coverage value, or "".


            The same decoder the live parser uses, so the two agree on

            this column as they do on every other. A result equal to the

            raw value is discarded - a copy is not a decode.

            """

            try:

                got = registry_binary_parser.render_registry_value(

                    table, name, data, vtype, _asep_env) or ''

            except Exception:

                return ''

            return '' if got == str(data) else got


        def _cov_ins(table, cols, values, key_cols):
            key_vals = tuple(values[cols.index(c)] for c in key_cols)
            if check_exists(cursor, table, list(key_cols), key_vals):
                return
            cursor.execute('INSERT INTO %s (%s) VALUES (%s)'
                           % (table, ", ".join(cols), ", ".join("?" * len(cols))), values)
            _cov_counts[table] = _cov_counts.get(table, 0) + 1

        def _cov_vals(hive, key):
            if not hive:
                return []
            out = []
            for n, v in (read_registry_values(hive, key) or {}).items():
                d, t = v if isinstance(v, tuple) else (v, "")
                out.append((_default_name(n), d, t))
            return out

        def _cov_one(hive, key, name):
            for n, d, t in _cov_vals(hive, key):
                if n.lower() == name.lower():
                    return d, True
            return None, False

        def _cov_subs(hive, key):
            if not hive:
                return []
            return get_subkeys(hive, key) or []

        def _cov_fmt(v):
            if isinstance(v, list):
                items = [str(x) for x in v]
                # The trailing empty strings are the MULTI_SZ NUL terminators.
                # Joining them produced "Terminal Server; Personal; ; " where the
                # live parser wrote "Terminal Server; Personal" - the same value,
                # spelled two ways, in three tables.
                while items and items[-1] == "":
                    items.pop()
                return "; ".join(items)
            return str(v)

        SW, SY = Software_reg_hive, system_reg_hive

        # ------------------------------------------------------------ posture
        POSTURE = [
            (SY, _cov_cs + r"\Control\SecurityProviders\WDigest", "UseLogonCredential", 1,
             "0 / absent", "1 caches plaintext credentials in LSASS memory",
             "credentials not cached in plaintext"),
            (SW, r"Microsoft\Windows\CurrentVersion\Policies\System", "EnableLUA", 0, "1",
             "0 disables UAC entirely", "UAC enabled"),
            (SW, r"Microsoft\Windows\CurrentVersion\Policies\System",
             "LocalAccountTokenFilterPolicy", 1, "0 / absent",
             "1 allows remote admin with local accounts (lateral movement)",
             "remote local-account admin restricted"),
            (SY, _cov_cs + r"\Control\Terminal Server", "fDenyTSConnections", 0, "1",
             "0 means RDP is accepting connections", "RDP disabled"),
            (SW, r"Policies\Microsoft\Windows Defender", "DisableAntiSpyware", 1,
             "0 / absent", "1 disables Defender", "Defender not disabled by policy"),
            (SW, r"Policies\Microsoft\Windows Defender\Real-Time Protection",
             "DisableRealtimeMonitoring", 1, "0 / absent",
             "1 disables real-time protection", "real-time protection not disabled"),
            (SW, r"Microsoft\Windows NT\CurrentVersion\SystemRestore", "DisableSR", 1,
             "0 / absent", "1 disables restore points, removing a recovery source",
             "system restore not disabled"),
        ]
        for hive, path, name, bad, dflt, weak, okmsg in POSTURE:
            v, present = _cov_one(hive, path, name)
            if not present:
                dec, assess, msg = "absent (Windows default)", "default", okmsg
            elif str(v) == str(bad):
                dec, assess, msg = str(v), "weakened", weak
            else:
                dec, assess, msg = str(v), "default", okmsg
            _cov_ins("SecurityPosture",
                     ["setting", "value_raw", "value_decoded", "default_value",
                      "assessment", "meaning", "key_path", "parsed_at"],
                     (name, "(absent)" if not present else str(v), dec, dflt, assess,
                      msg, path, _cov_stamp),
                     ["setting", "key_path"])

        v, present = _cov_one(SY, _cov_cs + r"\Control\FileSystem",
                              "NtfsDisableLastAccessUpdate")
        if present:
            try:
                _n = int(v)
                _dec = ("%s, last-access updates %s"
                        % ("system-managed" if _n & 0x80000000 else "user-set",
                           "ENABLED" if (_n & 0xF) in (0, 2) else "DISABLED"))
            except (TypeError, ValueError):
                _dec = "unknown"
        else:
            _dec = "absent"
        _cov_ins("SecurityPosture",
                 ["setting", "value_raw", "value_decoded", "default_value",
                  "assessment", "meaning", "key_path", "parsed_at"],
                 ("NtfsDisableLastAccessUpdate", "(absent)" if not present else str(v),
                  _dec, "0x80000002 (system-managed, enabled)", "informational",
                  "decides whether file last-access times are maintained",
                  _cov_cs + r"\Control\FileSystem", _cov_stamp),
                 ["setting", "key_path"])

        v, present = _cov_one(SY, _cov_cs + r"\Control\Lsa", "RunAsPPL")
        _cov_ins("SecurityPosture",
                 ["setting", "value_raw", "value_decoded", "default_value",
                  "assessment", "meaning", "key_path", "parsed_at"],
                 ("RunAsPPL", "(absent)" if not present else str(v),
                  {None: "absent", 0: "not protected", 1: "protected (UEFI lock)",
                   2: "protected (no UEFI lock)"}.get(v, str(v)), "absent or 0",
                  "hardened" if present and v in (1, 2) else "default",
                  "LSASS run as a protected process resists credential dumping",
                  _cov_cs + r"\Control\Lsa", _cov_stamp),
                 ["setting", "key_path"])

        for _name, _path in (("EnableScriptBlockLogging",
                              r"Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging"),
                             ("EnableModuleLogging",
                              r"Policies\Microsoft\Windows\PowerShell\ModuleLogging")):
            v, present = _cov_one(SW, _path, _name)
            _cov_ins("SecurityPosture",
                     ["setting", "value_raw", "value_decoded", "default_value",
                      "assessment", "meaning", "key_path", "parsed_at"],
                     (_name, "(absent)" if not present else str(v),
                      "enabled" if present and v == 1 else "not enabled",
                      "absent (off by default)",
                      "hardened" if present and v == 1 else "default",
                      "PowerShell logging is off unless enabled - absence limits "
                      "what evidence exists, it is not tampering", _path, _cov_stamp),
                     ["setting", "key_path"])

        v, present = _cov_one(SY, _cov_cs + r"\Control\Session Manager",
                              "PendingFileRenameOperations")
        if present and v:
            _items = [x for x in (v if isinstance(v, list) else [str(v)]) if x]
            for _i in range(0, len(_items) - 1, 2):
                _cov_ins("SecurityPosture",
                         ["setting", "value_raw", "value_decoded", "default_value",
                          "assessment", "meaning", "key_path", "parsed_at"],
                         ("PendingFileRenameOperations", _items[_i],
                          ("delete" if not _items[_i + 1] else "rename to " + _items[_i + 1]),
                          "absent", "informational",
                          "file operations queued for the next boot",
                          _cov_cs + r"\Control\Session Manager", _cov_stamp),
                         ["setting", "value_raw"])

        # OS build and edition - ProductName is frozen at "Windows 10" on Win11.
        _CV = r"Microsoft\Windows NT\CurrentVersion"
        for _n, _why in (("ProductName", "frozen at 'Windows 10' on Win11 - trust the build"),
                         ("CurrentBuild", "22000+ means Windows 11"),
                         ("DisplayVersion", "feature update level"),
                         ("EditionID", "SKU"),
                         ("InstallDate", "OS install time, Unix epoch")):
            _v, _p = _cov_one(SW, _CV, _n)
            if _p:
                _cov_ins("SecurityPosture",
                         ["setting", "value_raw", "value_decoded", "default_value",
                          "assessment", "meaning", "key_path", "parsed_at"],
                         (_n, str(_v), str(_v), "varies", "informational", _why,
                          _CV, _cov_stamp), ["setting", "key_path"])

        # Proxy configuration, the mirror of the prefetcher gap: the live parser
        # has always read these and this one never did. They are per-user, in
        # NTUSER, so every user hive is read rather than only the one whose
        # account happens to be first.
        _IS = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        for _nt in (ntuser_hives or []):
            for _n, _why in (("ProxyServer", "traffic routed through a proxy"),
                             ("ProxyEnable", "1 means the proxy above is in use")):
                _v, _p = _cov_one(_nt, _IS, _n)
                _cov_ins("SecurityPosture",
                         ["setting", "value_raw", "value_decoded", "default_value",
                          "assessment", "meaning", "key_path", "parsed_at"],
                         (_n, "(absent)" if not _p else str(_v),
                          "(absent)" if not _p else str(_v), "varies",
                          "informational", _why, _IS, _cov_stamp),
                         ["setting", "key_path"])

        for _n, _why in (("CrashDumpEnabled", "0 none, 1 complete, 2 kernel, 3 small, 7 automatic"),
                         ("DumpFile", "where a crash dump would be written")):
            _cc = _cov_cs + r"\Control\CrashControl"
            _v, _p = _cov_one(SY, _cc, _n)
            _cov_ins("SecurityPosture",
                     ["setting", "value_raw", "value_decoded", "default_value",
                      "assessment", "meaning", "key_path", "parsed_at"],
                     (_n, "(absent)" if not _p else str(_v),
                      "(absent)" if not _p else str(_v), "varies", "informational",
                      _why, _cc, _cov_stamp), ["setting", "key_path"])

        # r-strings cannot end in a backslash, so these paths are joined.
        BS = chr(92)
        for _which in ("Minimal", "Network"):
            _sb = _cov_cs + BS + "Control" + BS + "SafeBoot" + BS + _which
            _n_sb = len(_cov_subs(SY, _sb))
            _cov_ins("SecurityPosture",
                     ["setting", "value_raw", "value_decoded", "default_value",
                      "assessment", "meaning", "key_path", "parsed_at"],
                     ("SafeBoot\\" + _which, str(_n_sb), "%d entries" % _n_sb,
                      "varies by Windows build", "informational",
                      "services and drivers that still start in safe mode",
                      _sb, _cov_stamp), ["setting", "key_path"])

        # -------------------------------------------------- defender exclusions
        for _base, _src in ((r"Microsoft\Windows Defender\Exclusions", "local"),
                            (r"Policies\Microsoft\Windows Defender\Exclusions", "policy")):
            for _kind, _sing in (("Paths", "Path"), ("Extensions", "Extension"),
                                 ("Processes", "Process"), ("TemporaryPaths", "TemporaryPath")):
                for vn, vd, vt in _cov_vals(SW, _base + "\\" + _kind):
                    _cov_ins("DefenderExclusions",
                             ["exclusion_type", "value", "source", "key_path", "parsed_at"],
                             (_sing, vn, _src, _base + "\\" + _kind, _cov_stamp),
                             ["exclusion_type", "value"])

        # ----------------------------------------------------------- firewall
        _FW = (_cov_cs + r"\Services\SharedAccess\Parameters\FirewallPolicy\FirewallRules")
        for vn, vd, vt in _cov_vals(SY, _FW):
            f = {}
            for part in str(vd).split("|"):
                if "=" in part:
                    kk, _, vv = part.partition("=")
                    f.setdefault(kk, vv)
            _cov_ins("FirewallRules",
                     ["rule_type", "rule_name", "display_name", "action", "direction",
                      "enabled", "protocol", "local_port", "remote_port", "application",
                      "service", "profile", "key_path", "parsed_at"],
                     ("FirewallRule", vn, f.get("Name", ""), f.get("Action", ""),
                      f.get("Dir", ""), f.get("Active", ""), f.get("Protocol", ""),
                      f.get("LPort", ""), f.get("RPort", ""), f.get("App", ""),
                      f.get("Svc", ""), f.get("Profile", ""), _FW, _cov_stamp),
                     ["rule_type", "rule_name"])
        for _proto in ("v4tov4", "v4tov6", "v6tov4", "v6tov6"):
            for _tp in ("tcp", "udp"):
                _pp = _cov_cs + r"\Services\PortProxy\%s\%s" % (_proto, _tp)
                for vn, vd, vt in _cov_vals(SY, _pp):
                    _cov_ins("FirewallRules",
                             ["rule_type", "rule_name", "display_name", "action",
                              "direction", "enabled", "protocol", "local_port",
                              "remote_port", "application", "service", "profile",
                              "key_path", "parsed_at"],
                             ("PortProxy", vn, "%s -> %s" % (vn, vd), "Forward", "In",
                              "TRUE", _tp.upper(), vn, str(vd), "", "", _proto,
                              _pp, _cov_stamp),
                             ["rule_type", "rule_name"])

        # ------------------------------------------------------------- shares
        _SH = _cov_cs + r"\Services\LanmanServer\Shares"
        for vn, vd, vt in _cov_vals(SY, _SH):
            _parts = vd if isinstance(vd, list) else [str(vd)]
            _d = {}
            for _p in _parts:
                if "=" in _p:
                    kk, _, vv = _p.partition("=")
                    _d[kk] = vv
            _cov_ins("NetworkShares",
                     ["share_name", "share_path", "remark", "raw", "key_path", "parsed_at"],
                     (vn, _d.get("Path", ""), _d.get("Remark", ""), "; ".join(_parts),
                      _SH, _cov_stamp),
                     ["share_name"])

        # ------------------------------------------------------------ devices
        _WPD = r"Microsoft\Windows Portable Devices\Devices"
        for s in _cov_subs(SW, _WPD):
            fn, _p = _cov_one(SW, _WPD + "\\" + s, "FriendlyName")
            _cov_ins("ConnectedDevices",
                     ["device_type", "device_id", "friendly_name", "details",
                      "key_path", "parsed_at"],
                     ("PortableDevice", s, str(fn or ""), "", _WPD, _cov_stamp),
                     ["device_type", "device_id"])
        _BT = _cov_cs + r"\Services\BTHPORT\Parameters\Devices"
        for s in _cov_subs(SY, _BT):
            nm, _p = _cov_one(SY, _BT + "\\" + s, "Name")
            if isinstance(nm, bytes):
                nm = nm.split(b"\x00")[0].decode("utf-8", "ignore")
            _cov_ins("ConnectedDevices",
                     ["device_type", "device_id", "friendly_name", "details",
                      "key_path", "parsed_at"],
                     ("Bluetooth", s, str(nm or ""), "MAC address as key name",
                      _BT, _cov_stamp),
                     ["device_type", "device_id"])
        _EMD = r"Microsoft\Windows NT\CurrentVersion\EMDMgmt"
        for s in _cov_subs(SW, _EMD):
            _cov_ins("ConnectedDevices",
                     ["device_type", "device_id", "friendly_name", "details",
                      "key_path", "parsed_at"],
                     ("EMDMgmt", s, "", "volume serial and label history",
                      _EMD, _cov_stamp),
                     ["device_type", "device_id"])
        _SCSI = _cov_cs + r"\Enum\SCSI"
        for s in _cov_subs(SY, _SCSI):
            for inst in _cov_subs(SY, _SCSI + "\\" + s):
                fn, _p = _cov_one(SY, "%s\\%s\\%s" % (_SCSI, s, inst), "FriendlyName")
                _cov_ins("ConnectedDevices",
                         ["device_type", "device_id", "friendly_name", "details",
                          "key_path", "parsed_at"],
                         ("SCSI", "%s\\%s" % (s, inst), str(fn or ""), "",
                          _SCSI, _cov_stamp),
                         ["device_type", "device_id"])
        # Printers live in two places, and only one of them survives an image.
        # SYSTEM\...\Control\Print\Printers is built at boot and is not in the
        # hive file at all, so this pass found nothing and said nothing - the
        # offline parser reported no printers ever. The SOFTWARE copy under
        # Print\Printers is on disk and holds the same devices, so read both and
        # let the guarded insert dedupe.
        _PRN = _cov_cs + r"\Control\Print\Printers"
        for s in _cov_subs(SY, _PRN):
            port, _p = _cov_one(SY, _PRN + "\\" + s, "Port")
            _cov_ins("ConnectedDevices",
                     ["device_type", "device_id", "friendly_name", "details",
                      "key_path", "parsed_at"],
                     ("Printer", s, s, "port: %s" % (port or ""), _PRN, _cov_stamp),
                     ["device_type", "device_id"])
        _PRN_SW = r"Microsoft\Windows NT\CurrentVersion\Print\Printers"
        for s in _cov_subs(SW, _PRN_SW):
            port, _p = _cov_one(SW, _PRN_SW + "\\" + s, "Port")
            _cov_ins("ConnectedDevices",
                     ["device_type", "device_id", "friendly_name", "details",
                      "key_path", "parsed_at"],
                     ("Printer", s, s, "port: %s" % (port or ""), _PRN_SW, _cov_stamp),
                     ["device_type", "device_id"])

        # -------------------------------------------------- per-user artifacts
        for _nt_idx, _nt in enumerate(ntuser_hives or []):
            _u = user_identity.display_owner(_nt, _identity_accounts)
            _MP = r"Software\Microsoft\Windows\CurrentVersion\Explorer\MountPoints2"
            for s in _cov_subs(_nt, _MP):
                _kind = ("network share" if s.startswith("##")
                         else "volume GUID" if s.startswith("{") else "drive letter")
                _cov_ins("MountPoints2",
                         ["user_name", "mount_id", "mount_type", "key_path", "parsed_at"],
                         (_u, s, _kind, _MP, _cov_stamp), ["user_name", "mount_id"])

            _MND = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Map Network Drive MRU"
            for vn, vd, vt in _cov_vals(_nt, _MND):
                if vn == "MRUList":
                    continue
                _cov_ins("MountPoints2",
                         ["user_name", "mount_id", "mount_type", "key_path", "parsed_at"],
                         (_u, str(vd), "mapped network drive", _MND, _cov_stamp),
                         ["user_name", "mount_id"])

            _TSC = r"Software\Microsoft\Terminal Server Client"
            for vn, vd, vt in _cov_vals(_nt, _TSC + r"\Default"):
                _cov_ins("RDPClientMRU",
                         ["user_name", "entry_type", "server", "username_hint",
                          "key_path", "parsed_at"],
                         (_u, "MRU", str(vd), "", _TSC + r"\Default", _cov_stamp),
                         ["user_name", "entry_type", "server"])
            for s in _cov_subs(_nt, _TSC + r"\Servers"):
                hint, _p = _cov_one(_nt, _TSC + r"\Servers\\" + s, "UsernameHint")
                _cov_ins("RDPClientMRU",
                         ["user_name", "entry_type", "server", "username_hint",
                          "key_path", "parsed_at"],
                         (_u, "Server", s, str(hint or ""), _TSC + r"\Servers", _cov_stamp),
                         ["user_name", "entry_type", "server"])

            _OFF = r"Software\Microsoft\Office"
            for ver in _cov_subs(_nt, _OFF):
                for prod in _cov_subs(_nt, _OFF + "\\" + ver):
                    for leaf, kind in (("File MRU", "MRU"),
                                       (r"Security\Trusted Documents\TrustRecords", "TrustRecord")):
                        kp = "%s\\%s\\%s" % (_OFF + "\\" + ver, prod, leaf)
                        for vn, vd, vt in _cov_vals(_nt, kp):
                            _cov_ins("OfficeDocuments",
                                     ["user_name", "application", "version", "kind",
                                      "document", "raw", "key_path", "parsed_at"],
                                     (_u, prod, ver, kind,
                                      vn if kind == "TrustRecord" else str(vd),
                                      _cov_fmt(vd)[:400], kp, _cov_stamp),
                                     ["user_name", "application", "kind", "document"])

            _FU = r"Software\Microsoft\Windows\CurrentVersion\Explorer\FeatureUsage"
            for s in _cov_subs(_nt, _FU):
                for vn, vd, vt in _cov_vals(_nt, _FU + "\\" + s):
                    try:
                        _cnt = int(vd)
                    except (TypeError, ValueError):
                        _cnt = 0
                    _cov_ins("FeatureUsage",
                             ["user_name", "usage_type", "program", "count",
                              "key_path", "parsed_at"],
                             (_u, s, vn, _cnt, _FU + "\\" + s, _cov_stamp),
                             ["user_name", "usage_type", "program"])

            _CA = (r"Software\Microsoft\Windows NT\CurrentVersion"
                   r"\AppCompatFlags\Compatibility Assistant\Store")
            for vn, vd, vt in _cov_vals(_nt, _CA):
                _cov_ins("CompatibilityAssistant",
                         ["user_name", "program_path", "blob_size", "key_path", "parsed_at"],
                         (_u, vn, len(vd) if isinstance(vd, bytes) else 0, _CA, _cov_stamp),
                         ["user_name", "program_path"])

            _RA = r"Software\Microsoft\Windows\CurrentVersion\Search\RecentApps"
            for s in _cov_subs(_nt, _RA):
                _d = {a: b for a, b, _t in _cov_vals(_nt, _RA + "\\" + s)}
                _la = _d.get("LastAccessedTime")
                try:
                    _la = format_forensic_timestamp(
                        registry_binary_parser.filetime_to_datetime(int(_la))) if _la else ""
                except Exception:
                    _la = str(_la or "")
                _cov_ins("RecentApps",
                         ["user_name", "app_id", "app_path", "launch_count",
                          "last_accessed", "key_path", "parsed_at"],
                         (_u, str(_d.get("AppId", s)), str(_d.get("AppPath", "")),
                          int(_d.get("LaunchCount", 0) or 0), _la, _RA, _cov_stamp),
                         ["user_name", "app_id"])

            for _app, _rel, _art in (
                    ("PuTTY", r"Software\SimonTatham\PuTTY\Sessions", "session"),
                    ("PuTTY", r"Software\SimonTatham\PuTTY\SshHostKeys", "known host"),
                    ("WinSCP", r"Software\Martin Prikryl\WinSCP 2\Sessions", "session"),
                    ("WinRAR", r"Software\WinRAR\ArcHistory", "archive history"),
                    ("WinRAR", r"Software\WinRAR\DialogEditHistory\ExtrPath", "extract path"),
                    ("7-Zip", r"Software\7-Zip\Compression", "compression history"),
                    ("Sysinternals", r"Software\Sysinternals", "EULA accepted"),
                    ("TeamViewer", r"Software\TeamViewer", "config"),
                    ("FileZilla", r"Software\FileZilla Client", "config"),
                    ("VNC", r"Software\RealVNC", "config")):
                for vn, vd, vt in _cov_vals(_nt, _rel):
                    _cov_ins("ApplicationArtifacts",
                             ["user_name", "application", "artifact", "name", "value",
                              "key_path", "parsed_at"],
                             (_u, _app, _art, vn, _cov_fmt(vd)[:400], _rel, _cov_stamp),
                             ["user_name", "application", "artifact", "name"])
                for s in _cov_subs(_nt, _rel):
                    _cov_ins("ApplicationArtifacts",
                             ["user_name", "application", "artifact", "name", "value",
                              "key_path", "parsed_at"],
                             (_u, _app, _art, s, "", _rel, _cov_stamp),
                             ["user_name", "application", "artifact", "name"])

            # FileExts - the association the user picked beats the machine
            # default. UserChoice is the deliberate choice; the OpenWith lists
            # are only what was offered, so they stay distinguishable.
            _FEX = r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts"
            for _ext in _cov_subs(_nt, _FEX):
                _uc2, _p = _cov_one(_nt, f"{_FEX}\\{_ext}\\UserChoice", "ProgId")
                if _p and _uc2:
                    _cov_ins("file_exts",
                             ["user_name", "extension", "choice_type", "progid",
                              "key_path", "parsed_at"],
                             (_u, _ext, "UserChoice", str(_uc2),
                              f"{_FEX}\\{_ext}\\UserChoice", _cov_stamp),
                             ["user_name", "extension", "choice_type", "progid"])
                for vn, vd, vt in _cov_vals(_nt, f"{_FEX}\\{_ext}\\OpenWithProgids"):
                    _cov_ins("file_exts",
                             ["user_name", "extension", "choice_type", "progid",
                              "key_path", "parsed_at"],
                             (_u, _ext, "OpenWithProgids", vn,
                              f"{_FEX}\\{_ext}\\OpenWithProgids", _cov_stamp),
                             ["user_name", "extension", "choice_type", "progid"])
                for vn, vd, vt in _cov_vals(_nt, f"{_FEX}\\{_ext}\\OpenWithList"):
                    if vn == "MRUList":
                        continue
                    _cov_ins("file_exts",
                             ["user_name", "extension", "choice_type", "progid",
                              "key_path", "parsed_at"],
                             (_u, _ext, "OpenWithList", _cov_fmt(vd),
                              f"{_FEX}\\{_ext}\\OpenWithList", _cov_stamp),
                             ["user_name", "extension", "choice_type", "progid"])

            # CIDSizeMRU - apps that opened a common file dialog, newest first.
            # Decode the whole buffer as UTF-16 and cut at the first NUL
            # character: splitting the raw bytes on b"\x00\x00" lands on an odd
            # boundary and drops the last character ("brave.ex").
            _CID = (r"Software\Microsoft\Windows\CurrentVersion"
                    r"\Explorer\ComDlg32\CIDSizeMRU")
            _cidv = {vn: vd for vn, vd, vt in _cov_vals(_nt, _CID)}
            _ordr = _cidv.get("MRUListEx", b"")
            if isinstance(_ordr, bytes):
                for _pos in range(0, len(_ordr) // 4):
                    _idx = int.from_bytes(_ordr[_pos * 4:_pos * 4 + 4], "little")
                    if _idx == 0xFFFFFFFF:
                        break
                    _raw = _cidv.get(str(_idx))
                    if not isinstance(_raw, bytes):
                        continue
                    _app2 = _raw.decode("utf-16-le", "ignore").split("\x00")[0]
                    if not _app2:
                        continue
                    _cov_ins("cid_size_mru",
                             ["user_name", "position", "application", "key_path",
                              "parsed_at"],
                             (_u, _pos, _app2, _CID, _cov_stamp),
                             ["user_name", "application"])

            # ProgramsCache - Start menu program list as a shell-item blob.
            _SP2 = (r"Software\Microsoft\Windows\CurrentVersion"
                    r"\Explorer\StartPage2")
            for vn, vd, vt in _cov_vals(_nt, _SP2):
                if not str(vn).startswith("ProgramsCache"):
                    continue
                _cov_ins("programs_cache",
                         ["user_name", "value_name", "blob_size", "key_path",
                          "parsed_at"],
                         (_u, vn, len(vd) if isinstance(vd, bytes) else 0,
                          _SP2, _cov_stamp),
                         ["user_name", "value_name"])

            # Regedit LastKey - what this user last had selected in regedit.
            _RGE = (r"Software\Microsoft\Windows\CurrentVersion"
                    r"\Applets\Regedit")
            for vn, vd, vt in _cov_vals(_nt, _RGE):
                if vn not in ("LastKey", "View", "FindFlags"):
                    continue
                _cov_ins("regedit_lastkey",
                         ["user_name", "name", "value", "key_path", "parsed_at"],
                         (_u, vn, _cov_fmt(vd)[:400], _RGE, _cov_stamp),
                         ["user_name", "name", "value"])
            for vn, vd, vt in _cov_vals(_nt, _RGE + r"\Favorites"):
                _cov_ins("regedit_lastkey",
                         ["user_name", "name", "value", "key_path", "parsed_at"],
                         (_u, "Favorite: " + str(vn), _cov_fmt(vd)[:400],
                          _RGE + r"\Favorites", _cov_stamp),
                         ["user_name", "name", "value"])

            # Printers\Connections - network printers this user attached.
            _PRC = r"Printers\Connections"
            for _c in _cov_subs(_nt, _PRC):
                _parts = [p for p in str(_c).split(",") if p]
                _cov_ins("printer_connections",
                         ["user_name", "connection", "server", "printer",
                          "key_path", "parsed_at"],
                         (_u, _c, _parts[0] if _parts else "",
                          _parts[1] if len(_parts) > 1 else "", _PRC, _cov_stamp),
                         ["user_name", "connection"])

            # Explorer\Advanced - what the user could see. ShowSuperHidden=1 is
            # off by default, so switching it on means somebody went looking.
            _EXA = (r"Software\Microsoft\Windows\CurrentVersion"
                    r"\Explorer\Advanced")
            for _n, _dflt, _why in (
                    ("Hidden", "2", "1 shows hidden files, 2 hides them (default)"),
                    ("ShowSuperHidden", "0",
                     "1 reveals protected OS files - off by default"),
                    ("HideFileExt", "1",
                     "0 shows real extensions, 1 hides them (default)"),
                    ("StartMenuInit", "", "Start menu initialisation version")):
                _v, _p = _cov_one(_nt, _EXA, _n)
                if not _p:
                    continue
                _cov_ins("explorer_advanced",
                         ["user_name", "setting", "value", "value_decoded", "default_value",
                          "meaning", "key_path", "parsed_at"],
                         (_u, _n, str(_v), _cov_dec("explorer_advanced", _n, _v), _dflt, _why, _EXA, _cov_stamp),
                         ["user_name", "setting"])

        # ------------------------------------------------------- posture keys
        _RDPT = _cov_cs + r"\Control\Terminal Server\WinStations\RDP-Tcp"
        for _n, _dflt, _why in (
                ("PortNumber", "3389", "a non-3389 port hides RDP from a port scan"),
                ("UserAuthentication", "1", "0 disables NLA"),
                ("SecurityLayer", "2", "0 is RDP security, 2 is TLS"),
                ("fDisableCdm", "", "0 allows client drive mapping into the session"),
                ("MinEncryptionLevel", "3", "encryption strength")):
            _v, _p = _cov_one(SY, _RDPT, _n)
            if not _p:
                continue
            _cov_ins("rdp_tcp",
                     ["setting", "value", "value_decoded", "default_value", "meaning", "key_path",
                      "parsed_at"],
                     (_n, str(_v), _cov_dec("rdp_tcp", _n, _v), _dflt, _why, "SYSTEM\\" + _RDPT, _cov_stamp),
                     ["setting", "key_path"])

        # usbstor Start: 3 is the normal on-demand start, 4 is disabled - a
        # deliberate act that also stops USB history being written at all.
        _USBS = _cov_cs + r"\Services\usbstor"
        _v, _p = _cov_one(SY, _USBS, "Start")
        if _p:
            _cov_ins("usbstor_start",
                     ["setting", "value", "decoded", "default_value", "key_path",
                      "parsed_at"],
                     ("Start", str(_v),
                      {0: "boot", 1: "system", 2: "automatic", 3: "manual (normal)",
                       4: "DISABLED - USB storage blocked"}.get(_v, "unknown"),
                      "3", "SYSTEM\\" + _USBS, _cov_stamp),
                     ["setting", "key_path"])

        _WSH = r"Microsoft\Windows Script Host\Settings"
        # Only three values were read and a stock Windows 11 sets none of them,
        # so this table came out empty while the key held four others. Mirrors
        # the live parser value for value.
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
            _v, _p = _cov_one(SW, _WSH, _n)
            if not _p:
                continue
            _cov_ins("windows_script_host",
                     ["setting", "value", "value_decoded", "default_value", "meaning", "key_path",
                      "parsed_at"],
                     (_n, str(_v), _cov_dec("windows_script_host", _n, _v), "(absent = enabled)", _why,
                      "SOFTWARE\\" + _WSH, _cov_stamp),
                     ["setting", "key_path"])

        _DNSP = _cov_cs + r"\Services\Dnscache\Parameters"
        for vn, vd, vt in _cov_vals(SY, _DNSP):
            _cov_ins("dnscache_parameters",
                     ["name", "value", "value_decoded", "key_path", "parsed_at"],
                     (vn, _cov_fmt(vd)[:400], _cov_dec("dnscache_parameters", vn, vd), "SYSTEM\\" + _DNSP, _cov_stamp),
                     ["name", "key_path"])

        # FilesNotToSnapshot - files VSS drops from shadow copies. An added
        # entry removes the file from the very copies an examiner relies on.
        _FNTS = _cov_cs + r"\Control\BackupRestore\FilesNotToSnapshot"
        for _sub in _cov_subs(SY, _FNTS):
            for vn, vd, vt in _cov_vals(SY, f"{_FNTS}\\{_sub}"):
                _cov_ins("files_not_to_snapshot",
                         ["entry", "value", "key_path", "parsed_at"],
                         (f"{_sub}!{vn}", _cov_fmt(vd)[:400],
                          f"SYSTEM\\{_FNTS}\\{_sub}", _cov_stamp),
                         ["entry", "key_path"])
        for vn, vd, vt in _cov_vals(SY, _FNTS):
            _cov_ins("files_not_to_snapshot",
                     ["entry", "value", "key_path", "parsed_at"],
                     (vn, _cov_fmt(vd)[:400], "SYSTEM\\" + _FNTS, _cov_stamp),
                     ["entry", "key_path"])

        # Event log configuration, from the two places it actually lives.
        # The classic Security/System/Application logs are NOT under
        # WINEVT\Channels - they are legacy EventLog service keys. WINEVT holds
        # ~1166 Vista-era channels, ~788 disabled as shipped, so recording all
        # of them would bury the finding: take every classic log, every channel
        # an examiner asks about by name, and any channel someone has resized.
        _EVL = _cov_cs + r"\Services\EventLog"
        for _log in _cov_subs(SY, _EVL):
            _vals = {n: d for n, d, t in _cov_vals(SY, f"{_EVL}\\{_log}")}
            if not _vals:
                continue
            _cov_ins("winevt_channels",
                     ["channel", "source", "enabled", "max_size", "retention",
                      "log_file", "reason", "key_path", "parsed_at"],
                     (_log, "EventLog (classic)", "n/a",
                      str(_vals.get("MaxSize", "")), str(_vals.get("Retention", "")),
                      str(_vals.get("File", "")), "classic log",
                      f"SYSTEM\\{_EVL}\\{_log}", _cov_stamp),
                     ["channel", "source"])

        _WEVT = r"Microsoft\Windows\CurrentVersion\WINEVT\Channels"
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
        for _ch in _cov_subs(SW, _WEVT):
            _vals = {n: d for n, d, t in _cov_vals(SW, f"{_WEVT}\\{_ch}")}
            _watched = str(_ch).lower() in _watch_lower
            _resized = "MaxSize" in _vals
            if not (_watched or _resized):
                continue
            _cov_ins("winevt_channels",
                     ["channel", "source", "enabled", "max_size", "retention",
                      "log_file", "reason", "key_path", "parsed_at"],
                     (_ch, "WINEVT", str(_vals.get("Enabled", "")),
                      str(_vals.get("MaxSize", "")), str(_vals.get("Retention", "")),
                      "", "watched channel" if _watched else "non-default MaxSize",
                      f"SOFTWARE\\{_WEVT}\\{_ch}", _cov_stamp),
                     ["channel", "source"])

        # --------------------------------------------------- device attribution
        # WPDBUSENUM ties a USB volume GUID to the device behind it - the hop
        # between USBSTOR (which device) and MountedDevices (which letter).
        _WPD = _cov_cs + r"\Enum\SWD\WPDBUSENUM"
        for _dev in _cov_subs(SY, _WPD):
            _fn, _ = _cov_one(SY, f"{_WPD}\\{_dev}", "FriendlyName")
            _cov_ins("wpdbusenum",
                     ["device_id", "friendly_name", "volume_guid", "key_path",
                      "parsed_at"],
                     (_dev, str(_fn or ""),
                      str(_dev).split("#")[0] if "#" in str(_dev) else "",
                      f"SYSTEM\\{_WPD}\\{_dev}", _cov_stamp),
                     ["device_id"])

        # DeviceClasses: only the disk and volume classes. The full set is
        # thousands of rows of keyboards and audio endpoints.
        _DVC = _cov_cs + r"\Control\DeviceClasses"
        for _cls, _label in (
                ("{53f56307-b6bf-11d0-94f2-00a0c91efb8b}", "Disk"),
                ("{53f5630d-b6bf-11d0-94f2-00a0c91efb8b}", "Volume"),
                ("{53f56308-b6bf-11d0-94f2-00a0c91efb8b}", "Storage adapter"),
                ("{a5dcbf10-6530-11d2-901f-00c04fb951ed}", "USB device")):
            for _inst in _cov_subs(SY, f"{_DVC}\\{_cls}"):
                _cov_ins("device_classes",
                         ["class_guid", "class_name", "device_instance",
                          "key_path", "parsed_at"],
                         (_cls, _label, _inst, f"SYSTEM\\{_DVC}\\{_cls}", _cov_stamp),
                         ["class_guid", "device_instance"])

        # Two locations, and only the Explorer one was read - it does not exist
        # on Windows 11, where the cache lives under Windows Search and names
        # its values VolumeLabel/DriveType rather than _LabelFromReg/FileSystem.
        # Both are tried, both naming schemes accepted.
        for _VIC in (r"Microsoft\Windows Search\VolumeInfoCache",
                     r"Microsoft\Windows\CurrentVersion\Explorer\VolumeInfoCache"):
            for _drv in _cov_subs(SW, _VIC):
                _kp = f"{_VIC}\\{_drv}"
                _lbl, _ = _cov_one(SW, _kp, "VolumeLabel")
                if not _lbl:
                    _lbl, _ = _cov_one(SW, _kp, "_LabelFromReg")
                _fs, _ = _cov_one(SW, _kp, "FileSystem")
                if not _fs:
                    _dt, _ = _cov_one(SW, _kp, "DriveType")
                    _fs = {2: "Removable", 3: "Fixed", 4: "Network",
                           5: "CD-ROM", 6: "RAM disk"}.get(_dt, _dt)
                _cov_ins("volume_info_cache",
                         ["drive_letter", "volume_label", "file_system", "key_path",
                          "parsed_at"],
                         (_drv, str(_lbl or ""), str(_fs or ""),
                          f"SOFTWARE\\{_kp}", _cov_stamp),
                         ["drive_letter"])

        # ------------------------------------------------------- host identity
        _CRYP = r"Microsoft\Cryptography"
        _v, _p = _cov_one(SW, _CRYP, "MachineGuid")
        if _p:
            _cov_ins("machine_guid", ["name", "value", "key_path", "parsed_at"],
                     ("MachineGuid", str(_v), "SOFTWARE\\" + _CRYP, _cov_stamp),
                     ["name"])

        _PROD = _cov_cs + r"\Control\ProductOptions"
        for _n, _why in (("ProductType",
                          "WinNT is a workstation, ServerNT/LanmanNT a server"),
                         ("ProductSuite", "installed SKU suites")):
            _v, _p = _cov_one(SY, _PROD, _n)
            if _p:
                _cov_ins("product_options",
                         ["name", "value", "meaning", "key_path", "parsed_at"],
                         (_n, _cov_fmt(_v), _why, "SYSTEM\\" + _PROD, _cov_stamp),
                         ["name"])

        # SYSTEM\Setup keeps the in-place upgrade trail: which build the machine
        # came from, and when. Hive-relative, so no ControlSet prefix.
        _STP = "Setup"
        for vn, vd, vt in _cov_vals(SY, _STP):
            _cov_ins("os_install_history",
                     ["name", "value", "key_path", "parsed_at"],
                     (vn, _cov_fmt(vd)[:400], "SYSTEM\\" + _STP, _cov_stamp),
                     ["name", "key_path"])
        for _sub in _cov_subs(SY, _STP):
            if not str(_sub).lower().startswith("source os"):
                continue
            for vn, vd, vt in _cov_vals(SY, f"{_STP}\\{_sub}"):
                _cov_ins("os_install_history",
                         ["name", "value", "key_path", "parsed_at"],
                         (f"{_sub}!{vn}", _cov_fmt(vd)[:400],
                          f"SYSTEM\\{_STP}\\{_sub}", _cov_stamp),
                         ["name", "key_path"])

        _ACN = _cov_cs + r"\Control\ComputerName\ActiveComputerName"
        for vn, vd, vt in _cov_vals(SY, _ACN):
            _cov_ins("active_computer_name",
                     ["name", "value", "key_path", "parsed_at"],
                     (vn, _cov_fmt(vd), "SYSTEM\\" + _ACN, _cov_stamp), ["name"])

        # hivelist names the backing file of every loaded hive - how an examiner
        # confirms the hives collected are the ones that were in use.
        _HVL = _cov_cs + r"\Control\hivelist"
        for vn, vd, vt in _cov_vals(SY, _HVL):
            _cov_ins("hivelist", ["hive", "file_path", "key_path", "parsed_at"],
                     (vn, _cov_fmt(vd), "SYSTEM\\" + _HVL, _cov_stamp), ["hive"])

        _SENV = _cov_cs + r"\Control\Session Manager\Environment"
        for vn, vd, vt in _cov_vals(SY, _SENV):
            _cov_ins("system_environment",
                     ["name", "value", "value_decoded", "key_path", "parsed_at"],
                     (vn, _cov_fmt(vd)[:1000], _cov_dec("system_environment", vn, vd), "SYSTEM\\" + _SENV, _cov_stamp),
                     ["name"])

        _NETC = (_cov_cs + r"\Control\Network"
                           r"\{4d36e972-e325-11ce-bfc1-08002be10318}")
        for _ad in _cov_subs(SY, _NETC):
            if str(_ad).lower() == "descriptions":
                continue
            for _n in ("Name", "PnpInstanceID"):
                _v, _p = _cov_one(SY, f"{_NETC}\\{_ad}\\Connection", _n)
                if _p:
                    _cov_ins("network_adapters",
                             ["adapter_guid", "name", "value", "key_path",
                              "parsed_at"],
                             (_ad, _n, _cov_fmt(_v),
                              f"SYSTEM\\{_NETC}\\{_ad}\\Connection", _cov_stamp),
                             ["adapter_guid", "name"])

        _GPH = r"Microsoft\Windows\CurrentVersion\Group Policy\History"
        for _scope in _cov_subs(SW, _GPH):
            for _gpo in _cov_subs(SW, f"{_GPH}\\{_scope}"):
                for vn, vd, vt in _cov_vals(SW, f"{_GPH}\\{_scope}\\{_gpo}"):
                    _cov_ins("group_policy_history",
                             ["scope", "gpo_id", "name", "value", "key_path",
                              "parsed_at"],
                             (_scope, _gpo, vn, _cov_fmt(vd)[:400],
                              f"SOFTWARE\\{_GPH}\\{_scope}\\{_gpo}", _cov_stamp),
                             ["scope", "gpo_id", "name"])

        # MountedDevices -> USBStorageVolumes. The live parser has always read
        # this key; the offline one never did, so image cases lost the drive
        # letter / volume GUID binding with no error anywhere. It feeds the
        # existing USBStorageVolumes table rather than a new one, so both
        # acquisition paths produce the same schema.
        #
        # SYSTEM\MountedDevices is hive-relative and sits outside any ControlSet.
        try:
            _mdev_added = 0

            def _mdev_usbstor(raw):
                """(normalised device class, instance) for a USBSTOR binding."""
                try:
                    s = raw.decode("utf-16-le", "ignore") if isinstance(raw, bytes) \
                        else str(raw)
                except Exception:
                    return None
                sl = s.lower()
                if "usbstor#" not in sl:
                    return None
                start = sl.find("usbstor#") + len("usbstor#")
                end = sl.find("#{", start)
                if end == -1:
                    return None
                parts = s[start:end].split("#")
                if len(parts) < 2:
                    return None
                out = []
                for x in parts[0].split("&"):
                    xl = x.lower()
                    if xl.startswith("disk"):
                        out.append("Disk")
                    elif xl.startswith("ven_"):
                        out.append("Ven_" + x.split("_", 1)[1])
                    elif xl.startswith("prod_"):
                        out.append("Prod_" + x.split("_", 1)[1])
                    elif xl.startswith("rev_"):
                        out.append("Rev_" + x.split("_", 1)[1])
                    else:
                        out.append(x)
                return "&".join(out), parts[1]

            for vn, vd, vt in _cov_vals(SY, "MountedDevices"):
                _dl = _vg = ""
                if str(vn).startswith("\\DosDevices\\"):
                    _dl = str(vn)[12:]
                elif str(vn).startswith("\\??\\Volume"):
                    _vg = str(vn)[11:]
                else:
                    continue
                if not isinstance(vd, bytes):
                    continue
                _ex = _mdev_usbstor(vd)
                if not _ex:
                    continue
                _cand = "%s\\%s" % _ex
                if check_exists(cursor, "USBStorageVolumes",
                                ["device_id", "volume_guid"], (_cand, _vg)):
                    continue
                cursor.execute(
                    "INSERT OR IGNORE INTO USBStorageVolumes "
                    "(device_id, volume_guid, volume_name, drive_letter, parsed_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (_cand, _vg, "", _dl, _cov_stamp))
                _mdev_added += 1
            _cov_counts["USBStorageVolumes(MountedDevices)"] = _mdev_added
        except Exception as e:
            logging.error("Error reading MountedDevices (offline): %s", e)

        # PrefetchParameters: the other live-only gap. 0 means prefetch is off,
        # so an absent Prefetch directory is configuration, not wiping.
        _PFP = (_cov_cs + r"\Control\Session Manager\Memory Management"
                          r"\PrefetchParameters")
        for _n, _why in (("EnablePrefetcher",
                          "0 off, 1 app, 2 boot, 3 both (default)"),
                         ("EnableSuperfetch", "SysMain/Superfetch state")):
            _v, _p = _cov_one(SY, _PFP, _n)
            if not _p:
                continue
            _cov_ins("SecurityPosture",
                     ["setting", "value_raw", "value_decoded", "default_value",
                      "assessment", "meaning", "key_path", "parsed_at"],
                     (_n, str(_v), str(_v), "3",
                      "weakened" if str(_v) == "0" else "informational",
                      _why, "SYSTEM\\" + _PFP, _cov_stamp),
                     ["setting", "key_path"])

        conn.commit()
        print("[OK] Forensic coverage collected: %d rows (%s)"
              % (sum(_cov_counts.values()),
                 ", ".join("%s=%d" % (k, v) for k, v in sorted(_cov_counts.items()))))

    except Exception as e:
        logging.error(f"Error collecting forensic coverage (offline): {e}")
        print(f"Warning: Could not collect forensic coverage data: {e}")

    # ========================================================================
    # PHASE: User identity
    #
    # Builds UserAccounts (SAM + ProfileList merged) and rewrites every raw SID
    # into "SID (MACHINE\username)". Shared with the live parser so both agree.
    # ========================================================================
    print("\n[IDENTITY] Building user accounts...")
    try:
        _accts, _enriched = user_identity.apply_identity(
            cursor, sam_reg_hive, Software_reg_hive, system_reg_hive)
        conn.commit()
        _machine = user_identity.get_machine_name(system_reg_hive)
        print(f"[OK] User accounts: {_accts} ({_machine or 'unknown machine'}), "
              f"{_enriched} SID references resolved to names")
    except Exception as e:
        logging.error(f"Error building user identity (offline): {e}")
        print(f"Warning: Could not build user identity: {e}")

    # ========================================================================
    # PHASE: SECURITY hive
    #
    # LSA policy, audit policy and secret metadata. Same function the live
    # parser calls - only the hive path differs, so both produce the same
    # tables from the same code.
    # ========================================================================
    print("\n[SECURITY] Reading LSA policy and audit policy...")
    try:
        _sec_counts = security_hive.parse_security(
            cursor, security_reg_hive, check_exists,
            format_forensic_timestamp(get_current_utc()))
        conn.commit()
        if any(_sec_counts.values()):
            print("[OK] SECURITY hive: "
                  + ", ".join("%s=%d" % (k, v)
                              for k, v in sorted(_sec_counts.items())))
        else:
            print("[--] No SECURITY hive in this collection - LSA tables empty")
    except Exception as e:
        logging.error(f"Error parsing SECURITY hive (offline): {e}")
        print(f"Warning: Could not parse SECURITY hive: {e}")

    # --------------------------------------------- walking the allocator
    # One pass per hive collects everything a tree walk cannot reach: class
    # names, the shared security descriptors, and the keys and values still
    # present in freed cells.
    #
    # This walks the same hive the rest of the parse read - the recovered copy
    # where one was made - so every table in the case describes one state.
    # Measured either way, the difference is small and goes in both directions:
    # replaying SOFTWARE loses 2 carved keys and gains 6 carved values out of
    # 1,451 and 6,347.
    print("\n[Structure] Walking hive allocators for class names, "
          "security descriptors and freed cells...")
    try:
        _walk_stamp = get_current_forensic_timestamp()
        _walk_targets = []
        for _label, _path in (("SYSTEM", system_reg_hive),
                              ("SOFTWARE", Software_reg_hive),
                              ("SAM", sam_reg_hive),
                              ("SECURITY", security_reg_hive),
                              ("DEFAULT", default_reg_hive)):
            if _path:
                _walk_targets.append((_label, _path))
        for _i, _p in enumerate(ntuser_hives or []):
            _walk_targets.append(("NTUSER.DAT" if _i == 0 else "NTUSER.DAT[%d]" % _i, _p))
        for _i, _p in enumerate(usrclass_hives or []):
            _walk_targets.append(("UsrClass.dat" if _i == 0 else "UsrClass.dat[%d]" % _i, _p))

        _tot = {"c": 0, "s": 0, "k": 0, "v": 0}
        # Kept so the attribution pass below can reuse them rather than
        # walking every hive a second time.
        _walk_results = {}
        for _label, _path in _walk_targets:
            _w = registry_hive_walk.walk_hive(_path)
            _walk_results[_label] = _w
            if _w.error:
                logging.debug("hive walk %s: %s", _label, _w.error)

            for _cn in _w.class_names:
                cursor.execute(
                    'INSERT OR IGNORE INTO registry_class_names (hive_name, key_path, '
                    'key_name, class_name, class_length, key_last_write, '
                    'parsed_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                    (_label, _cn["key_path"], _cn["key_name"], _cn["class_name"],
                     _cn["class_length"],
                     format_forensic_timestamp(_cn["timestamp"]) if _cn["timestamp"] else "",
                     _walk_stamp))
                _tot["c"] += cursor.rowcount if cursor.rowcount > 0 else 0

            for _sd in _w.security:
                _d = registry_binary_parser.parse_security_descriptor(_sd["descriptor"])
                cursor.execute(
                    'INSERT OR IGNORE INTO registry_security_descriptors (hive_name, '
                    'sk_offset, descriptor_hash, reference_count, owner_sid, '
                    'group_sid, dacl_ace_count, sacl_ace_count, '
                    'descriptor_size, sample_key_path, parsed_at) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (_label, _sd["sk_offset"],
                     hashlib.sha256(_sd["descriptor"]).hexdigest(),
                     _sd["reference_count"],
                     _d.get("owner_sid", ""), _d.get("group_sid", ""),
                     _d.get("dacl_ace_count"), _d.get("sacl_ace_count"),
                     _d.get("size", 0), _sd["sample_key_path"], _walk_stamp))
                _tot["s"] += cursor.rowcount if cursor.rowcount > 0 else 0

            for _ck in _w.carved_keys:
                # A carved key keeps its own last-written time, which dates the
                # activity rather than the deletion - often the more useful half.
                _when = ""
                if _ck["timestamp_raw"]:
                    try:
                        _when = format_forensic_timestamp(
                            filetime_to_datetime(_ck["timestamp_raw"]))
                    except Exception:
                        _when = ""
                cursor.execute(
                    'INSERT OR IGNORE INTO registry_carved_keys (hive_name, '
                    'cell_offset, key_name, key_path, parent_resolved, '
                    'key_last_write, subkey_count, value_count, record_state, '
                    'parsed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (_label, _ck["cell_offset"], _ck["key_name"],
                     _ck.get("key_path", ""),
                     1 if _ck.get("parent_resolved") else 0, _when,
                     _ck["subkey_count"], _ck["value_count"], DELETED_STATE,
                     _walk_stamp))
                # The values this key held, recovered through its own value
                # list. A deleted key with no values is a name and a date.
                for _kv in _ck.get("values", []):
                    cursor.execute(
                        'INSERT OR IGNORE INTO registry_carved_values (hive_name, '
                        'cell_offset, parent_cell_offset, key_path, value_name, '
                        'value_type, data_size, is_inline, data, record_state, '
                        'parsed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        (_label, _kv["cell_offset"], _ck["cell_offset"],
                         _ck.get("key_path", ""), _kv["value_name"],
                         _REG_TYPE_NAMES.get(_kv["value_type"], "UNKNOWN"),
                         _kv["data_size"], 1 if _kv["inline"] else 0,
                         _carved_data_text(_kv.get("data"), _kv["value_type"]),
                         DELETED_STATE, _walk_stamp))
                    _tot["v"] += cursor.rowcount if cursor.rowcount > 0 else 0
                _tot["k"] += cursor.rowcount if cursor.rowcount > 0 else 0

            for _cv in _w.carved_values:
                # A freed value reached without the key that owned it: no
                # path, because the key that would give it one is gone.
                cursor.execute(
                    'INSERT OR IGNORE INTO registry_carved_values (hive_name, '
                    'cell_offset, parent_cell_offset, key_path, value_name, '
                    'value_type, data_size, is_inline, data, record_state, '
                    'parsed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (_label, _cv["cell_offset"], None, "", _cv["value_name"],
                     _REG_TYPE_NAMES.get(_cv["value_type"], "UNKNOWN"),
                     _cv["data_size"], 1 if _cv["inline"] else 0,
                     _carved_data_text(_cv.get("data"), _cv["value_type"]),
                     DELETED_STATE, _walk_stamp))
                _tot["v"] += cursor.rowcount if cursor.rowcount > 0 else 0

        conn.commit()
        print("[OK] Allocator walk: %d class names, %d security descriptors, "
              "%d carved keys, %d carved values"
              % (_tot["c"], _tot["s"], _tot["k"], _tot["v"]))

        # ---- which value changed, and in which transaction ---------------
        # The one thing the hive alone cannot say. Each pending transaction's
        # dirty pages are diffed against the hive, and a value sitting on a
        # byte that differs is a value that genuinely changed. The diff is what
        # makes it worth having: a dirty page is 4 KB and holds dozens of
        # records, so taking the page as the unit implicates roughly seventy
        # times more data than actually moved.
        _changes = 0
        _change_hives = 0
        try:
            for _label, _path in sorted(_pre_replay.items()):
                if not _path or not os.path.exists(_path):
                    continue
                try:
                    _rows = registry_hive_walk.value_changes(_path)
                except Exception as _exc:
                    logging.debug("value changes %s: %s", _label, _exc)
                    continue
                if _rows:
                    _change_hives += 1
                for _r in _rows:
                    # Exact, and only where the transaction's own pages show
                    # the owning key's time actually moved. A key whose nk
                    # merely sits on a dirty page reads back what the hive
                    # already said, and reporting that as an exact time would
                    # relabel the bound as a measurement.
                    _ca = ""
                    if _r.get("changed_at_raw"):
                        try:
                            _ca = format_forensic_timestamp(
                                filetime_to_datetime(_r["changed_at_raw"]))
                        except Exception:
                            _ca = ""
                    _kw = ""
                    if _r.get("key_last_write_raw"):
                        try:
                            _kw = format_forensic_timestamp(
                                filetime_to_datetime(_r["key_last_write_raw"]))
                        except Exception:
                            _kw = ""
                    cursor.execute(
                        'INSERT OR IGNORE INTO registry_value_changes ('
                        'hive_name, transaction_sequence, change_kind, changed_at, key_path, '
                        'value_name, value_type, changed_before, changed_after, '
                        'value_before, changed_bytes, cell_offset, key_last_write, '
                        'parsed_at) '
                        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        (_label, _r["sequence"], _r["change_kind"], _ca,
                         _r["key_path"], _r["value_name"],
                         _REG_TYPE_NAMES.get(_r.get("value_type"), "UNKNOWN"),
                         _r["changed_before"], _r["changed_after"],
                         _r["value_before"], _r["changed_bytes"], _r["offset"],
                         _kw, _walk_stamp))
                    _changes += cursor.rowcount if cursor.rowcount > 0 else 0
            conn.commit()
        except Exception as _exc:
            logging.debug("value change pass: %s", _exc)
        print("[OK] Value changes from transaction logs: %d across %d hive(s)"
              % (_changes, _change_hives))


        # ---- the keys nothing used to read ---------------------------------
        # Nineteen keys that hold real data and were opened by nothing. One of
        # them corrects a finding rather than adding one: StartupApproved says
        # whether each autostart entry is allowed to launch, and without it every
        # Run value is reported as live persistence.
        try:
            _cs = active_controlset or "ControlSet001"

            def _vals(path):
                try:
                    return read_registry_values(_hive_for(path), _strip(path)) or {}
                except Exception:
                    return {}

            def _subs(path):
                try:
                    return get_subkeys(_hive_for(path), _strip(path)) or []
                except Exception:
                    return []

            # Each collector is handed a path already carrying its hive tag, so one
            # pair of readers can serve keys that live in different hives.
            def _hive_for(path):
                tag = path.split("|", 1)[0]
                return {"SYSTEM": system_reg_hive, "SOFTWARE": Software_reg_hive,
                        "NTUSER": (ntuser_hives or [None])[0]}.get(tag)

            def _strip(path):
                body = path.split("|", 1)[1] if "|" in path else path
                return body

            def _sys(rel):
                return "SYSTEM|" + _cs + chr(92) + rel

            def _sw(rel):
                return "SOFTWARE|" + rel

            def _nt(rel):
                return "NTUSER|" + rel

            K = registry_extra_keys.KEYS
            _resolved = {
                "power": _sys(K["power"]), "nls_language": _sys(K["nls_language"]),
                "w32time": _sys(K["w32time"]), "tcpip": _sys(K["tcpip"]),
                "search_gather": _sw(K["search_gather"]),
                "winnt_current_version": _sw(K["winnt_current_version"]),
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
                # remember: the tag is how a path is routed to a reader, never
                # what gets stored.
                registry_extra_keys.with_display_paths(rows)
                marks = ", ".join("?" * (len(columns) + 1))
                sql = ("INSERT OR IGNORE INTO %s (%s, parsed_at) VALUES (%s)"
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

            _put("app_paths", ["app_name", "executable_path", "app_dir", "key_path"],
                 registry_extra_keys.app_paths(_vals, _subs, _sw(K["app_paths"])))

            _put("safe_boot_services",
                 ["boot_mode", "entry_name", "entry_type", "key_path"],
                 registry_extra_keys.safe_boot_services(
                     _vals, _subs, _sys(K["safe_boot"])))

            _put("zone_map",
                 ["scope", "host", "protocol", "zone", "zone_name", "key_path"],
                 registry_extra_keys.zone_map(_vals, _subs, _nt(K["zone_map"])))

            _put("app_permissions",
                 ["capability", "app", "packaged", "permission", "last_used_start",
                  "last_used_stop", "key_path"],
                 registry_extra_keys.app_permissions(
                     _vals, _subs, _sw(K["consent_store"])))

            _put("shared_dlls", ["dll_path", "reference_count", "key_path"],
                 registry_extra_keys.shared_dlls(_vals, _sw(K["shared_dlls"])))

            _put("hid_devices",
                 ["device_id", "instance_id", "device_desc", "manufacturer",
                  "service", "key_path"],
                 registry_extra_keys.hid_devices(_vals, _subs, _sys(K["hid"])))

            _put("network_cards",
                 ["card_index", "description", "service_name", "key_path"],
                 registry_extra_keys.network_cards(
                     _vals, _subs, _sw(K["network_cards"])))

            _put("system_configuration",
                 ["setting", "value_raw", "value_decoded", "area", "meaning",
                  "key_path"],
                 registry_extra_keys.system_configuration(_vals, _resolved))

            # SecurityPosture is guarded, not constrained - it predates _put
            # and declares no UNIQUE, so OR IGNORE has nothing to act on and
            # would append these five settings on every re-parse. Adding a
            # UNIQUE would not fix it either: CREATE TABLE IF NOT EXISTS leaves
            # every case already on disk without one. So the guard goes here,
            # the way the other ten writers do it.
            _sp_cols = ["setting", "value_raw", "value_decoded",
                        "default_value", "assessment", "meaning", "key_path"]
            for _row in registry_extra_keys.with_display_paths(
                    registry_extra_keys.security_posture(_vals, _resolved)):
                if check_exists(cursor, "SecurityPosture",
                                ["setting", "key_path"],
                                (_row.get("setting"), _row.get("key_path"))):
                    continue
                cursor.execute(
                    "INSERT INTO SecurityPosture (%s, parsed_at) VALUES (%s)"
                    % (", ".join(_sp_cols), ", ".join("?" * (len(_sp_cols) + 1))),
                    tuple(_row.get(c) for c in _sp_cols) + (_walk_stamp,))
                _extra["n"] += 1

            # ---- feed the correction back into the persistence table --
            # A Run value is a request; StartupApproved is the answer. Without
            # this, six entries on the reference system read as live
            # persistence while Explorer has refused to launch them since
            # February.
            #
            # A row with no matching approval entry is "unknown", never
            # "enabled": most autostart locations have no StartupApproved
            # equivalent, and calling them enabled asserts something unrecorded.
            try:
                cursor.execute("UPDATE AutoStartPrograms SET startup_state = "
                               "'unknown' WHERE startup_state IS NULL")
                _marked = 0
                for _st, _at, _nm, _sc in cursor.execute(
                        "SELECT state, disabled_at, entry_name, scope "
                        "FROM startup_approved").fetchall():
                    # Matched within the matching location, so a Run entry
                    # cannot be marked from a StartupFolder one of the same name.
                    _like = "%" + str(_sc).replace("StartupFolder", "Startup") + "%"
                    cursor.execute(
                        "UPDATE AutoStartPrograms SET startup_state = ?, "
                        "disabled_at = ? WHERE program_name = ? "
                        "AND location LIKE ?",
                        (_st, _at or "", _nm, _like))
                    _marked += cursor.rowcount if cursor.rowcount > 0 else 0
                conn.commit()
                if _marked:
                    print("     %d AutoStartPrograms row(s) carry their real "
                          "enabled/disabled state" % _marked)
            except Exception as _exc:
                logging.debug("autostart state pass: %s", _exc)

            conn.commit()
            _dis = cursor.execute(
                "SELECT COUNT(*) FROM startup_approved WHERE state = 'disabled'"
            ).fetchone()[0]
            print("[OK] Previously unread keys: %d rows" % _extra["n"])
            if _dis:
                print("     %d autostart entr%s disabled - AutoStartPrograms marks "
                      "them" % (_dis, "y is" if _dis == 1 else "ies are"))
        except Exception as _exc:
            logging.debug("extra key pass: %s", _exc)

        # ---- when was this written, and how well do we know -------------
        # A key's last-write time is an UPPER BOUND on every value it holds:
        # writing any value updates its key, so no value can be newer than its
        # key, and at most one value actually matches it - and not even that
        # one for certain, because adding a subkey moves the key's time too.
        #
        # So a value row never carries a key time as though it were its own.
        # last_written holds the time, time_basis says what kind of time it is,
        # and the display prefixes "<=" for a bound. The Run key on the machine
        # this was written against has one timestamp and two values that
        # changed in different transactions - one number on both rows is wrong
        # for at least one of them, and nothing in the hive says which.
        _KEY_ROOTS = re.compile(
            r"^(root|cmi-createhive\{[^}]*\}|\$\$\$proto\.hiv|system|software|"
            r"sam|security|default|ntuser\.dat|usrclass\.dat|hklm|hkcu|hku|"
            r"hkey_local_machine|hkey_current_user|hkey_users)$")

        def _norm_key(path):
            parts = [x for x in (path or "").replace("/", chr(92)).split(chr(92)) if x]
            while parts and _KEY_ROOTS.match(parts[0].lower()):
                parts.pop(0)
            return chr(92).join(parts).lower()

        def _key_columns(cur):
            """(table, key column) for every table that names its rows' key.

            The two passes below both need this list, and deriving it from the
            live schema rather than a hardcoded list means a table added later
            is covered without anyone remembering to come back here.
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

        _key_rows = 0
        _timed = {"exact": 0, "bound": 0, "none": 0}
        try:
            _key_time = {}
            for _label, _path in sorted(_pre_replay.items()):
                if not _path or not os.path.exists(_path):
                    continue
                for _kt in registry_hive_walk.key_times(_path):
                    if not _kt["key_path"]:
                        continue
                    _when = ""
                    if _kt["timestamp_raw"]:
                        try:
                            _when = format_forensic_timestamp(
                                filetime_to_datetime(_kt["timestamp_raw"]))
                        except Exception:
                            _when = ""
                    if _when:
                        # The same path exists in several hives - one per user
                        # profile, plus DEFAULT - and an artifact row does not
                        # always say which one it came from. Where they
                        # disagree, take the LATEST: an upper bound that is too
                        # late is still a true bound, one that is too early is
                        # a false claim about when a value could have been
                        # written. 131 rows differed from their key's recorded
                        # time before this, all of them collisions of this kind.
                        _nk = _norm_key(_kt["key_path"])
                        _prev = _key_time.get(_nk)
                        if _prev is None or _when > _prev[2]:
                            _key_time[_nk] = (_label, _kt["key_path"], _when,
                                              _kt["cell_offset"])
            # Held in memory, written out below - but only for the keys
            # something in this case actually refers to. A hive set has around
            # half a million keys, and storing all of them turned a 30,000-row
            # case into a 520,000-row one whose key tab nobody could read.
            _wanted = set()
            for _t, _kc in _key_columns(cursor):
                try:
                    for (_kp,) in cursor.execute(
                            "SELECT DISTINCT [%s] FROM [%s]" % (_kc, _t)):
                        if _kp:
                            _wanted.add(_norm_key(_kp))
                except Exception:
                    continue
            for _norm in _wanted:
                _hit = _key_time.get(_norm)
                if not _hit:
                    continue
                cursor.execute(
                    'INSERT OR IGNORE INTO registry_key_times (hive_name, '
                    'key_path, key_last_write, cell_offset, parsed_at) '
                    'VALUES (?, ?, ?, ?, ?)',
                    (_hit[0], _hit[1], _hit[2], _hit[3], _walk_stamp))
                _key_rows += cursor.rowcount if cursor.rowcount > 0 else 0
            conn.commit()

            # Attributed changes beat the bound wherever the log named a value.
            _exact = {}
            try:
                for _kp, _vn, _at in cursor.execute(
                        'SELECT key_path, value_name, changed_at FROM '
                        'registry_value_changes WHERE changed_at IS NOT NULL '
                        'AND changed_at <> ""').fetchall():
                    _exact.setdefault((_norm_key(_kp), (_vn or "").lower()), _at)
            except Exception:
                pass

            # Every table that records which key its rows came from.
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
                    _norm = _norm_key(_kp)
                    if not _norm:
                        # No key recorded for this row, so there is no bound to
                        # give it. A hive root normalises to the empty string
                        # too, and without this every row with a blank key_path
                        # silently inherited the root's timestamp - 131 rows in
                        # AutoStartPrograms alone, each of them a confident
                        # claim about a key nobody wrote down.
                        _timed["none"] += 1
                        continue
                    _hit = _exact.get((_norm, _vn.lower()))
                    if _hit:
                        _updates.append((_hit, "value (txn log)", _rid))
                        _timed["exact"] += 1
                        continue
                    _bound = _key_time.get(_norm)
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
        except Exception as _exc:
            logging.debug("time basis pass: %s", _exc)
        print("[OK] Key times: %d keys; value rows dated: %d exact, %d bounded, "
              "%d without a key" % (_key_rows, _timed["exact"], _timed["bound"],
                                    _timed["none"]))

        # ---- deleted autostart entries, put where they will be seen ------
        # A carved key is attributed ONLY when its reconstructed path matches a
        # path this parser collects AutoStartPrograms from. No path, no
        # attribution: a carved key whose parent chain broke could have been
        # anywhere, and guessing is how a recovered artefact becomes a wrong
        # conclusion.
        _autostart_paths = {
            "microsoft\\windows\\currentversion\\run": "Run",
            "microsoft\\windows\\currentversion\\runonce": "RunOnce",
        }
        _deleted_asep = 0
        try:
            for _label, _walked in _walk_results.items():
                _scope = "HKCU" if _label.startswith(("NTUSER", "UsrClass")) else "HKLM"
                for _ck in _walked.carved_keys:
                    _path = (_ck.get("key_path") or "").lower().lstrip("\\")
                    # The hive's own root is not part of the path an autostart
                    # location is named by, so match on the tail.
                    _hit = None
                    for _needle, _kind in _autostart_paths.items():
                        if _path.endswith(_needle):
                            _hit = _kind
                            break
                    if not _hit:
                        continue
                    for _kv in _ck.get("values", []):
                        _cmd = _carved_data_text(_kv.get("data"), _kv["value_type"])
                        _loc = "%s %s" % (_scope, _hit)
                        if check_exists(cursor, 'AutoStartPrograms',
                                        ['location', 'program_name'],
                                        (_loc, _kv["value_name"])):
                            continue
                        cursor.execute(
                            'INSERT INTO AutoStartPrograms (location, '
                            'program_name, command, record_state, parsed_at) '
                            'VALUES (?, ?, ?, ?, ?)',
                            (_loc, _kv["value_name"], _cmd, DELETED_STATE,
                             _walk_stamp))
                        _deleted_asep += 1
            if _deleted_asep:
                print("[OK] %d deleted autostart entr%s recovered into "
                      "AutoStartPrograms" % (_deleted_asep,
                                             "y" if _deleted_asep == 1 else "ies"))
            conn.commit()
        except Exception as e:
            logging.error("Could not attribute carved autostart entries: %s", e)

    except Exception as e:
        logging.error("Hive allocator walk failed: %s", e)
        print("Warning: allocator walk did not complete: %s" % e)

    # ------------------------------------------------------- hive provenance
    try:
        _hs_stamp = get_current_forensic_timestamp()
        for _st in _hive_states:
            # Guarded like every other insert here: the table carries no UNIQUE
            # constraint, so OR IGNORE would be a no-op and re-parsing the same
            # case would append the same hive state again. Keyed on the hive and
            # its sequence numbers - re-parsing unchanged evidence is a no-op,
            # while a hive that has moved on since gets a new row.
            if check_exists(cursor, 'registry_hive_state',
                            ['hive_name', 'hive_path', 'sequence_1',
                             'sequence_2', 'replayed'],
                            (_st.hive_name, _st.hive_path, _st.sequence_1,
                             _st.sequence_2, 1 if _st.recovered else 0)):
                continue
            cursor.execute(
                'INSERT INTO registry_hive_state (hive_name, hive_path, '
                'sequence_1, sequence_2, was_dirty, logs_found, log_format, '
                'replayed, entries_applied, pages_applied, highest_sequence, '
                'source_sha256, acquisition_route, reason, parsed_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (_st.hive_name, _st.hive_path, _st.sequence_1, _st.sequence_2,
                 1 if _st.was_dirty else 0,
                 "; ".join(os.path.basename(x) for x in _st.logs_found),
                 _st.log_format, 1 if _st.recovered else 0,
                 _st.entries_applied, _st.pages_applied, _st.highest_sequence,
                 # The hash of the file as found. Recovery works on a copy, so
                 # this is what the evidence still hashes to afterwards.
                 # An offline parse reads a hive the collector already
                 # acquired, so the route is settled before the parser sees it.
                 _st.source_sha256, "file:collected", _st.reason, _hs_stamp))
        _stale = [x for x in _hive_states if x.was_dirty and not x.recovered]
        if _stale:
            print("[WARNING] %d hive(s) were dirty and could not be replayed; "
                  "their rows may not be the final registry state:" % len(_stale))
            for _st in _stale:
                print("    %s - %s" % (_st.hive_name, _st.reason))
    except Exception as e:
        logging.error("Could not record registry_hive_state: %s", e)

    # ========================================================================
    # FINAL SUMMARY
    # ========================================================================

    conn.commit()
    
    # Count total records across all tables
    total_records = 0
    try:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table[0]}")
            count = cursor.fetchone()[0]
            total_records += count
    except Exception as e:
        logging.error(f"Error counting records: {e}")
        total_records = 0
    
    conn.close()

    print("\n" + "=" * 80)
    print("FORENSIC REGISTRY ANALYSIS COMPLETE")
    print("=" * 80)
    print(f"\n[OK] Database: {db_path}")
    print(f"[OK] Tables Created: 40+")
    print(f"[OK] Artifact Types: 20+")
    print(f"[OK] Data Fields: 100+")
    print(f"[OK] Registry Paths: 55+")
    print(f"[OK] Total Records: {total_records:,}")
    
    # Report processed hive types
    if offline_mode and case_root:
        print(f"\n[OK] Processed Hives:")
        if ntuser_hives:
            print(f"    - NTUSER.DAT: {len(ntuser_hives)} file(s)")
        if usrclass_hives:
            print(f"    - UsrClass.dat: {len(usrclass_hives)} file(s)")
        if system_reg_hive:
            print(f"    - SYSTEM: 1 file")
        if Software_reg_hive:
            print(f"    - SOFTWARE: 1 file")
    
    print(f"\n[OK] Capabilities:")
    print("    - USB device tracking with serial numbers")
    print("    - Program execution timeline (UserAssist/DAM/BAM)")
    print("    - Folder access history (Shellbags from NTUSER + UsrClass)")
    print("    - Document access patterns (OpenSave/LastVisit MRU)")
    print("    - System services and persistence mechanisms")
    print("    - Software inventory and malware detection")
    print("    - Browser and navigation history")
    print("    - Network configuration and WiFi timeline")
    print("    - Windows Update status and system health")
    print("    - Malware indicators with risk scoring")
    print(f"\n[OK] Errors logged to: offline_regclaw_errors.log")
    print("\n" + "=" * 80)

    # The recovered copies are NOT removed here any more, and that is
    # deliberate. They used to belong to this parse, and a recovered SYSTEM
    # left behind is a second copy of the registry sitting in the temp folder.
    # But ShimCache, AmCache, SRUM, the SECURITY hive and user identity now
    # read the same recovered hives, and several of them run after this parser
    # - deleting the workspace here would make each of them replay the same
    # files again.
    #
    # registry_transaction_log owns the workspace and registers it with atexit,
    # so nothing outlives the process. It is memoised, so within a run it holds
    # one copy per hive rather than one per parser. A caller that wants the
    # space back sooner can call registry_transaction_log.reset_replay_cache().

    # Return dictionary format expected by parser invoker
    return {
        'success': True,
        'records': total_records,
        'output_path': db_path
    }

if __name__ == "__main__":
    reg_Claw()

