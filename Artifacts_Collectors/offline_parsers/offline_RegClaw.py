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

import sqlite3
import os
import datetime
import logging
import struct
from Registry import Registry

# Import registry_binary_parser with fallback
try:
    from Artifacts_Collectors import registry_binary_parser
except ModuleNotFoundError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from Artifacts_Collectors import registry_binary_parser

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
                     'UsrClass.SAV', 'usrclass.sav', 'UsrClass.BAK', 'usrclass.bak']
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
                data = value.value()
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
                path_values[name] = (data, value_type_str)
            
            if path_values:
                logging.debug(f"Successfully read from: {path}")
                successful_paths.append(path)
                
                # Merge values (prefer values from earlier paths, i.e., active ControlSet)
                for name, value_tuple in path_values.items():
                    if name not in merged_values:
                        merged_values[name] = value_tuple
        
        except Exception as e:
            logging.debug(f"Path not found: {path}")
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
                data = value.value()
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
                    data = value.value()
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
        ("machine_run", "name TEXT, row_data TEXT, type TEXT"),
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
        ("Network_list", "subkey TEXT, name TEXT, data TEXT, type TEXT, "
                         "network_name TEXT, connection_date TEXT, "
                         "gateway_mac TEXT, is_hidden INTEGER"),
        # 'type' matches the live schema. Without it the inserts below - which
        # named a non-existent column - failed inside a try/except and left both
        # tables empty in every offline case.
        ("computer_Name", "name TEXT, row_data TEXT, type TEXT"),
        ("time_zone", "name TEXT, row_data TEXT, type TEXT"),
        # Raw layer for keys whose structured tables already exist here. The
        # live parser creates all four; offline created none, so the same
        # machine yielded a different schema depending on how it was acquired.
        ("network_interfaces", "subkey TEXT, name TEXT, row_data TEXT, type TEXT"),
        ("shutdown_information", "name TEXT, row_data TEXT, type TEXT"),
        ("Windows_lastupdate", "name TEXT, row_data TEXT, type TEXT"),
        ("Windows_lastupdate_subkeys", "subkey TEXT, name TEXT, row_data TEXT, type TEXT"),
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
        bias INTEGER, active_time_bias INTEGER, parsed_at TEXT
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS NetworkInterfacesInfo (
        interface_id TEXT, ip_address TEXT, subnet_mask TEXT,
        default_gateway TEXT, dhcp_enabled INTEGER, dhcp_server TEXT,
        dns_servers TEXT, mac_address TEXT, parsed_at TEXT
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS WindowsUpdateInfo (
        last_check_time TEXT, last_install_time TEXT, au_options INTEGER,
        scheduled_install_day INTEGER, scheduled_install_time INTEGER, parsed_at TEXT
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ShutdownInfo (
        shutdown_time TEXT, shutdown_count INTEGER, shutdown_type TEXT, clean_shutdown INTEGER,
        parsed_at TEXT
    )''')

    # DAM and BAM
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS DAM (
        subkey TEXT, name TEXT, row_data TEXT, type TEXT, app_name TEXT,
        process_path TEXT, sid TEXT, last_execution TEXT,
        execution_count INTEGER, parsed_at TEXT
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS BAM (
        subkey TEXT, name TEXT, row_data TEXT, type TEXT, app_name TEXT,
        process_path TEXT, sid TEXT, last_execution TEXT,
        execution_flags INTEGER, parsed_at TEXT
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
        registry_path TEXT, parent_path TEXT, parsed_at TEXT, user_name TEXT
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
        extension TEXT, drive_letter TEXT, access_date TEXT, row_data TEXT,
        parsed_at TEXT, user_name TEXT
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS LastSaveMRU (
        mru_number TEXT, type TEXT, application TEXT, folder_path TEXT,
        folder_name TEXT, drive_letter TEXT, access_date TEXT, row_data TEXT,
        parsed_at TEXT, user_name TEXT
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
    for _mru_t in ("RunMRU", "WordWheelQuery"):
        try:
            cursor.execute("PRAGMA table_info(%s)" % _mru_t)
            _mc = [c[1] for c in cursor.fetchall()]
            if _mc and "key_last_write" not in _mc:
                cursor.execute(
                    "ALTER TABLE %s ADD COLUMN key_last_write TEXT" % _mru_t)
        except sqlite3.Error as _e:
            logging.debug("key_last_write migration for %s: %s", _mru_t, _e)

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
        location TEXT, program_name TEXT, command TEXT, parsed_at TEXT,
        PRIMARY KEY (location, program_name)
    )''')

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
                    
                    # Also populate AutoStartPrograms table
                    full_location = f"{location}\\{auto_type}"
                    if not check_exists(cursor, 'AutoStartPrograms', ['location', 'program_name'], (full_location, name)):
                        cursor.execute('''INSERT INTO AutoStartPrograms
                            (location, program_name, command, parsed_at)
                            VALUES (?, ?, ?, ?)''',
                            (full_location, name, command_str, get_current_forensic_timestamp()))

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
                        
                        # Also populate AutoStartPrograms table
                        full_location = f"{location}\\{auto_type}"
                        if not check_exists(cursor, 'AutoStartPrograms', ['location', 'program_name'], (full_location, name)):
                            cursor.execute('''INSERT INTO AutoStartPrograms
                                (location, program_name, command, parsed_at)
                                VALUES (?, ?, ?, ?)''',
                                (full_location, name, command_str, get_current_forensic_timestamp()))

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
                        cursor.execute('''INSERT INTO DAM
                            (subkey, name, row_data, type, app_name, process_path, sid, last_execution, execution_count, parsed_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                            (subkey, name, str(data)[:200], value_type, app_name, process_path, sid,
                             last_execution, execution_count, get_current_forensic_timestamp()))
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
                    # Initialize default values
                    process_path = name
                    app_name = os.path.basename(name) if name else ''
                    last_execution = ''
                    execution_flags = 0
                    
                    # Parse binary data for timestamp
                    if value_type == "REG_BINARY":
                        binary_data = data if isinstance(data, bytes) else data.encode('latin-1')
                        try:
                            parsed_data = registry_binary_parser.parse_bam_entry(name, binary_data)
                            process_path = parsed_data.get('process_path', name)
                            last_execution = parsed_data.get('last_execution', '')
                            app_name = os.path.basename(process_path)
                        except Exception as e:
                            logging.error(f"Error parsing BAM binary data for {name}: {e}")
                    
                    # Extract execution_flags from 'Flags' value if present
                    if 'Flags' in values:
                        try:
                            flags_data, flags_type = values['Flags']
                            if isinstance(flags_data, int):
                                execution_flags = flags_data
                            elif isinstance(flags_data, bytes) and len(flags_data) >= 4:
                                execution_flags = struct.unpack('<I', flags_data[:4])[0]
                            else:
                                execution_flags = int(flags_data)
                        except Exception as e:
                            logging.debug(f"Could not parse execution_flags for {name}: {e}")
                            execution_flags = 0

                    # Extract SID from subkey path
                    sid = _extract_sid_from_path(subkey)
                    
                    # Insert into database
                    if not check_exists(cursor, 'BAM', ['subkey', 'name'], (subkey, name)):
                        cursor.execute('''INSERT INTO BAM
                            (subkey, name, row_data, type, app_name, process_path, sid, last_execution, execution_flags, parsed_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                            (subkey, name, str(data)[:200], value_type, app_name, process_path, sid,
                             last_execution, execution_flags, get_current_forensic_timestamp()))
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

    # PHASE: Shellbags
    print("[SHELLBAGS] Collecting folder access history...")
    
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
            
            # Collect all values from this subkey
            subkey_values = {}
            for value in current_key.values():
                name = value.name()
                data = value.value()
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
                        
                        registry_path = full_path

                        if not check_exists(cursor, 'Shellbags', ['file_name', 'registry_path', 'user_name'],
                                           (file_name, registry_path, _sb_user)):
                            cursor.execute('''INSERT INTO Shellbags
                                (file_name, short_name, shell_item_type, mru_position,
                                 created_date, modified_date, accessed_date, attributes,
                                 file_size, special_folder, network_share, server_name,
                                 share_name, drive_letter, mft_record_number,
                                 registry_path, parent_path, parsed_at, user_name)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                                (file_name, short_name, shell_item_type, mru_position,
                                 created_date, modified_date, accessed_date, attributes,
                                 file_size, special_folder, network_share, server_name,
                                 share_name, drive_letter, mft_record_number,
                                 registry_path, parent_readable,
                                 get_current_forensic_timestamp(), _sb_user))
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
                    for name, (data, value_type) in values.items():
                        if name.lower() == 'mrulistex' or value_type != "REG_BINARY":
                            continue
                        try:
                            if isinstance(data, bytes):
                                parsed_data = registry_binary_parser.parse_opensavemru_entry(data)
                                file_name = parsed_data.get('file_name', '')
                                if not check_exists(cursor, 'OpenSaveMRU', ['subkey', 'name', 'file_name', 'user_name'], (ext_subkey, name, file_name, _hive_user)):
                                    cursor.execute('''INSERT INTO OpenSaveMRU
                                        (subkey, name, type, file_path, file_name, extension, drive_letter, access_date, row_data, parsed_at, user_name)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                                        (ext_subkey, name, value_type, parsed_data.get('file_path', ''), file_name, ext_subkey,
                                         parsed_data.get('drive_letter', ''), parsed_data.get('access_date', ''), str(data)[:100], get_current_forensic_timestamp(), _hive_user))
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
                for name, (data, value_type) in lastsave_values.items():
                    if name.lower() == 'mrulistex' or value_type != "REG_BINARY":
                        continue
                    try:
                        if isinstance(data, bytes):
                            parsed_data = registry_binary_parser.parse_lastsavemru_entry(data)
                            app = parsed_data.get('application', '')
                            if not check_exists(cursor, 'LastSaveMRU', ['mru_number', 'application', 'user_name'], (name, app, _hive_user)):
                                cursor.execute('''INSERT INTO LastSaveMRU
                                    (mru_number, type, application, folder_path, folder_name, drive_letter, access_date, row_data, parsed_at, user_name)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                                    (name, value_type, app, parsed_data.get('folder_path', ''), parsed_data.get('file_name', ''),
                                     parsed_data.get('drive_letter', ''), '', str(data)[:100], get_current_forensic_timestamp(), _hive_user))
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
                                          (term, 'General', -1, None, _ww_kw, get_current_forensic_timestamp(), _hive_user))
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

        for device_id, values in usb_devices.items():
            try:
                description = values.get('Description', ('', 'REG_SZ'))[0] if 'Description' in values else ''
                manufacturer = values.get('Mfg', ('', 'REG_SZ'))[0] if 'Mfg' in values else ''
                friendly_name = values.get('FriendlyName', ('', 'REG_SZ'))[0] if 'FriendlyName' in values else description
                
                # Extract VID and PID from device ID
                vid, pid = extract_vid_pid(device_id)
                
                # Get last connected time if available
                last_connected = ""
                if 'LastConnected' in values:
                    last_connected = values['LastConnected'][0]
                    # Try to parse as FILETIME if it's binary
                    if isinstance(last_connected, bytes) and len(last_connected) == 8:
                        try:
                            from Artifacts_Collectors.registry_binary_parser import parse_filetime
                            last_connected = parse_filetime(last_connected)
                        except:
                            last_connected = ""

                if not check_exists(cursor, 'USBDevices', ['device_id'], (device_id,)):
                    # Fold parse time into description to match live schema
                    desc_with_timestamp = f'{description} {{"timestamp": "{get_current_forensic_timestamp()}"}}'
                    cursor.execute('''INSERT INTO USBDevices
                        (device_id, description, manufacturer, friendly_name, last_connected)
                        VALUES (?, ?, ?, ?, ?)''',
                        (device_id, desc_with_timestamp, str(manufacturer), str(friendly_name),
                         str(last_connected)))
                
                # 2. USB Properties (USBProperties table)
                # Collect all properties for this device
                for prop_name, (prop_value, prop_type) in values.items():
                    if prop_name not in ['', None]:
                        prop_type_str = str(prop_type)
                        prop_value_str = str(prop_value)
                        
                        if not check_exists(cursor, 'USBProperties', 
                                          ['device_id', 'property_name'], 
                                          (device_id, prop_name)):
                            cursor.execute('''INSERT INTO USBProperties
                                (device_id, property_name, property_value, property_type)
                                VALUES (?, ?, ?, ?)''',
                                (device_id, prop_name, prop_value_str, prop_type_str))
                
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

                            # 4a. USB Storage Devices table
                            if not check_exists(cursor, 'USBStorageDevices', ['device_id'], (device_id,)):
                                cursor.execute('''INSERT INTO USBStorageDevices
                                    (device_id, friendly_name, serial_number, vendor_id, product_id, revision, parsed_at)
                                    VALUES (?, ?, ?, ?, ?, ?, ?)''',
                                    (device_id, friendly_name, serial_number, vendor_id,
                                     product_id, revision, get_current_forensic_timestamp()))
                            
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
                        estimated_size = values.get('EstimatedSize', (0, 'REG_DWORD'))[0] if 'EstimatedSize' in values else 0

                        display_name_str = str(display_name)
                        if display_name_str and not check_exists(cursor, 'InstalledSoftware', ['display_name'], (display_name_str,)):
                            # Fold estimated_size into last TEXT column to match live schema
                            ts = get_current_forensic_timestamp()
                            ts_with_size = f'{ts} {{"estimated_size": "{estimated_size}"}}'
                            cursor.execute('''INSERT INTO InstalledSoftware
                                (display_name, display_version, publisher, install_date, install_location, uninstall_string, parsed_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?)''',
                                (display_name_str, str(display_version), str(publisher), str(install_date),
                                 str(install_location), str(uninstall_string), ts_with_size))

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
                display_name = values.get('DisplayName', ('', 'REG_SZ'))[0] if 'DisplayName' in values else service_name
                description = values.get('Description', ('', 'REG_SZ'))[0] if 'Description' in values else ''
                image_path = values.get('ImagePath', ('', 'REG_SZ'))[0] if 'ImagePath' in values else ''
                start_type = values.get('Start', (0, 'REG_DWORD'))[0] if 'Start' in values else 0
                service_type = values.get('Type', (0, 'REG_DWORD'))[0] if 'Type' in values else 0
                error_control = values.get('ErrorControl', (0, 'REG_DWORD'))[0] if 'ErrorControl' in values else 0

                # Convert start_type to text
                start_type_map = {0: 'Boot', 1: 'System', 2: 'AutoStart', 3: 'Manual', 4: 'Disabled'}
                start_type_text = start_type_map.get(start_type, f'Unknown({start_type})')

                # Determine status
                status = "Active" if start_type in [0, 2] else "Inactive"

                if not check_exists(cursor, 'SystemServices', ['service_name'], (service_name,)):
                    # Fold start_type_text into description
                    desc_with_sysType = f'{description} {{"start_type_text": "{start_type_text}"}}'
                    cursor.execute('''INSERT INTO SystemServices
                        (service_name, display_name, description, image_path, start_type, service_type,
                         error_control, status, parsed_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (service_name, str(display_name), desc_with_sysType, str(image_path),
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
        
        for network_list_path in network_list_paths:
            try:
                logging.debug(f"Checking Network Lists path: {network_list_path}")
                network_profiles = get_subkeys(Software_reg_hive, network_list_path)
                
                if network_profiles:
                    logging.debug(f"Successfully read Network Lists from: {network_list_path}")
            
                for profile_guid, values in network_profiles.items():
                    try:
                        profile_name = values.get('ProfileName', ('', 'REG_SZ'))[0] if 'ProfileName' in values else ''
                        description = values.get('Description', ('', 'REG_SZ'))[0] if 'Description' in values else ''
                        category = values.get('Category', (0, 'REG_DWORD'))[0] if 'Category' in values else 0
                        date_created = values.get('DateCreated', ('', 'REG_BINARY'))[0] if 'DateCreated' in values else ''
                        date_last_connected = values.get('DateLastConnected', ('', 'REG_BINARY'))[0] if 'DateLastConnected' in values else ''
                        
                        # For Signatures paths, also extract SSID and DefaultGatewayMac
                        ssid = values.get('FirstNetwork', ('', 'REG_SZ'))[0] if 'FirstNetwork' in values else ''
                        default_gateway_mac = values.get('DefaultGatewayMac', ('', 'REG_BINARY'))[0] if 'DefaultGatewayMac' in values else ''
                        
                        # Convert category to text
                        category_map = {0: 'Public', 1: 'Private', 2: 'Domain'}
                        category_text = category_map.get(category, f'Unknown({category})')
                        
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
                        def _nl(value_name, value):
                            if not value:
                                return
                            if check_exists(cursor, 'Network_list',
                                            ['subkey', 'name', 'data'],
                                            (profile_guid, value_name, str(value))):
                                return
                            cursor.execute(
                                'INSERT INTO Network_list (subkey, name, data, type, '
                                'network_name, connection_date, gateway_mac, is_hidden) '
                                'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                                (profile_guid, value_name, str(value), 'REG_SZ',
                                 str(profile_name), date_last_connected_str,
                                 formatted_mac, 0))

                        _nl('ProfileName', profile_name)
                        _nl('Category', category_text)
                        _nl('DateCreated', date_created_str)
                        _nl('DateLastConnected', date_last_connected_str)
                        _nl('SSID', ssid)
                        _nl('DefaultGatewayMac', formatted_mac)
                        
                    except Exception as e:
                        logging.error(f"Error with network profile {profile_guid}: {e}")
            except Exception as e:
                logging.debug(f"NetworkList path unavailable: {network_list_path}")
        
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
        for interface_id, values in network_interfaces.items():
            for _vn, _vt in values.items():
                try:
                    _d, _t = _vt if isinstance(_vt, tuple) else (_vt, '')
                    if not check_exists(cursor, 'network_interfaces',
                                        ['subkey', 'name'],
                                        (str(interface_id), str(_vn))):
                        cursor.execute(
                            'INSERT INTO network_interfaces '
                            '(subkey, name, row_data, type) VALUES (?, ?, ?, ?)',
                            (str(interface_id), str(_vn), str(_d), str(_t)))
                except Exception as e:
                    logging.debug(f"raw network_interfaces {interface_id}/{_vn}: {e}")

        for interface_id, values in network_interfaces.items():
            try:
                ip_address = values.get('DhcpIPAddress', values.get('static IPAddress', ('', 'REG_SZ')))[0] if 'DhcpIPAddress' in values or 'static IPAddress' in values else ''
                subnet_mask = values.get('DhcpSubnetMask', values.get('static SubnetMask', ('', 'REG_SZ')))[0] if 'DhcpSubnetMask' in values or 'static SubnetMask' in values else ''
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
                                return ", ".join(str(x) for x in _v)
                            return _v
                    return ''

                default_gateway = _first('DefaultGateway', 'static DefaultGateway',
                                         'DhcpDefaultGateway')
                dhcp_enabled = values.get('EnableDHCP', (1, 'REG_DWORD'))[0] if 'EnableDHCP' in values else 1
                dhcp_server = values.get('DhcpServer', ('', 'REG_SZ'))[0] if 'DhcpServer' in values else ''
                dns_servers = _first('NameServer', 'DhcpNameServer', 'DhcpNameServers')

                # An interface with no IP is still an interface, and its DNS
                # servers and gateway can still matter. Gating on ip_address
                # dropped six of this machine's ten interfaces, so the offline
                # parser reported four where the live one reported ten.
                if not check_exists(cursor, 'NetworkInterfacesInfo', ['interface_id'], (interface_id,)):
                    cursor.execute('''INSERT INTO NetworkInterfacesInfo
                        (interface_id, ip_address, subnet_mask, default_gateway, dhcp_enabled, dhcp_server, dns_servers, parsed_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                        (interface_id, str(ip_address), str(subnet_mask), str(default_gateway),
                         int(dhcp_enabled), str(dhcp_server), str(dns_servers), get_current_forensic_timestamp()))
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
            product_name = current_version_values.get('ProductName', ('', 'REG_SZ'))[0] if 'ProductName' in current_version_values else ''
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
            
            # Fold product_name into parsed_at to match live schema
            ts = get_current_forensic_timestamp()
            ts_with_productName = f'{ts} {{"product_name": "{product_name}"}}'
            if not check_exists(cursor, 'ComputerNameInfo', ['computer_name'], (str(computer_name),)):
                cursor.execute('''INSERT OR IGNORE INTO ComputerNameInfo
                    (computer_name, registered_owner, registered_organization, product_id, installation_date, parsed_at)
                    VALUES (?, ?, ?, ?, ?, ?)''',
                    (str(computer_name), str(registered_owner), str(registered_organization),
                     str(product_id), install_date_str, ts_with_productName))
            
            # Also populate the raw computer_Name table (column is row_data,
            # not data - the old name silently discarded every row).
            if not check_exists(cursor, 'computer_Name', ['name'], ('ComputerName',)):
                cursor.execute('INSERT INTO computer_Name (name, row_data, type) VALUES (?, ?, ?)',
                             ('ComputerName', str(computer_name), 'REG_SZ'))
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
            
            if not check_exists(cursor, 'TimeZoneInfo', ['time_zone_name'], (str(time_zone_name),)):
                cursor.execute('''INSERT OR IGNORE INTO TimeZoneInfo
                    (time_zone_name, standard_name, daylight_name, bias, active_time_bias, parsed_at)
                    VALUES (?, ?, ?, ?, ?, ?)''',
                    (str(time_zone_name), str(standard_name), str(daylight_name),
                     int(bias), int(active_time_bias), get_current_forensic_timestamp()))
            
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
                    'INSERT INTO time_zone (name, row_data, type) VALUES (?, ?, ?)',
                    (str(_tz_name), str(_tz_data), str(_tz_type)))
        except Exception as e:
            logging.debug(f"TimeZone path unavailable: {e}")
        
        # User Profiles
        try:
            profile_list_path = "Microsoft\\Windows NT\\CurrentVersion\\ProfileList"
            profile_list_subkeys = get_subkeys(Software_reg_hive, profile_list_path)
            
            for user_sid, values in profile_list_subkeys.items():
                try:
                    profile_image_path = values.get('ProfileImagePath', ('', 'REG_SZ'))[0] if 'ProfileImagePath' in values else ''
                    profile_loaded = values.get('State', (0, 'REG_DWORD'))[0] if 'State' in values else 0
                    
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
            au_options = winupdate_values.get('AUOptions', (1, 'REG_DWORD'))[0] if 'AUOptions' in winupdate_values else 1

            au_options_map = {1: 'Not configured', 2: 'Disabled', 3: 'Auto-notify', 4: 'Auto-download and install'}
            au_options_text = au_options_map.get(int(au_options), f'Unknown({au_options})')

            scheduled_install_day = winupdate_values.get('ScheduledInstallDay', (0, 'REG_DWORD'))[0] if 'ScheduledInstallDay' in winupdate_values else 0
            scheduled_install_time = winupdate_values.get('ScheduledInstallTime', (0, 'REG_DWORD'))[0] if 'ScheduledInstallTime' in winupdate_values else 0

            # Fold au_options_text into parsed_at to match live schema
            ts = get_current_forensic_timestamp()
            ts_with_auOptions = f'{ts} {{"au_options_text": "{au_options_text}"}}'
            if not check_exists(cursor, 'WindowsUpdateInfo', ['last_check_time'], (str(last_check_time),)):
                cursor.execute('''INSERT OR IGNORE INTO WindowsUpdateInfo
                    (last_check_time, last_install_time, au_options, scheduled_install_day, scheduled_install_time, parsed_at)
                    VALUES (?, ?, ?, ?, ?, ?)''',
                    (str(last_check_time), str(last_install_time), int(au_options),
                     int(scheduled_install_day), int(scheduled_install_time), ts_with_auOptions))

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
                                '(subkey, name, row_data, type) VALUES (?, ?, ?, ?)',
                                (str(_sk), str(_vn), str(_d), str(_t)))
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

            if not check_exists(cursor, 'ShutdownInfo', ['shutdown_time'], (shutdown_time,)):
                cursor.execute('''INSERT OR IGNORE INTO ShutdownInfo
                    (shutdown_time, parsed_at)
                    VALUES (?, ?)''',
                    (shutdown_time, get_current_forensic_timestamp()))

            # Raw layer for the same key.
            for _vn, _vt in (shutdown_values or {}).items():
                try:
                    _d, _t = _vt if isinstance(_vt, tuple) else (_vt, '')
                    if not check_exists(cursor, 'shutdown_information',
                                        ['name'], (str(_vn),)):
                        cursor.execute(
                            'INSERT INTO shutdown_information '
                            '(name, row_data, type) VALUES (?, ?, ?)',
                            (str(_vn), str(_d), str(_t)))
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
                                   (location, program_name, command, parsed_at)
                                   VALUES (?, ?, ?, ?)""",
                                ("TaskCache" + task_path,
                                 task_path.rsplit("\\", 1)[-1], full, stamp))
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
                'hive TEXT, key_path TEXT, name TEXT, data TEXT, type TEXT, '
                'user_name TEXT, parsed_at TEXT)')

        _asep_cs = get_active_controlset(system_reg_hive) if system_reg_hive else "ControlSet001"
        _asep_stamp = format_forensic_timestamp(get_current_utc())
        _asep_count = 0

        def _asep_fmt(data):
            # REG_MULTI_SZ arrives as a list; join rather than store a repr, so
            # the column matches what the live parser writes.
            if isinstance(data, list):
                return "; ".join(str(x) for x in data)
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
                cursor.execute(
                    f'INSERT INTO {table} (hive, key_path, name, data, type, '
                    'user_name, parsed_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                    (hive_label, key_path, name, value, rtype, _owner, _asep_stamp))
                _asep_count += 1
            if roll_up and value:
                loc = roll_up if not user_name else f"HKU\\{user_name} {roll_up}"
                if not check_exists(cursor, 'AutoStartPrograms',
                                    ['location', 'program_name'], (loc, name)):
                    cursor.execute(
                        'INSERT INTO AutoStartPrograms '
                        '(location, program_name, command, parsed_at) '
                        'VALUES (?, ?, ?, ?)', (loc, name, value, _asep_stamp))

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
            # UsrClass.dat lives under <profile>\AppData\Local\Microsoft\Windows,
            # so the profile directory name is the username. Walk up rather than
            # guess: basename is "Windows", not the user.
            _uname = None
            try:
                _p = os.path.normpath(_uc).split(os.sep)
                if "AppData" in _p:
                    _uname = _p[_p.index("AppData") - 1]
            except Exception:
                _uname = None
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
                assessment TEXT, meaning TEXT, key_path TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS DefenderExclusions (
                exclusion_type TEXT, value TEXT, source TEXT, key_path TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS FirewallRules (
                rule_type TEXT, rule_name TEXT, display_name TEXT, action TEXT,
                direction TEXT, enabled TEXT, protocol TEXT, local_port TEXT,
                remote_port TEXT, application TEXT, service TEXT, profile TEXT,
                key_path TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS NetworkShares (
                share_name TEXT, share_path TEXT, remark TEXT, raw TEXT,
                key_path TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS ConnectedDevices (
                device_type TEXT, device_id TEXT, friendly_name TEXT, details TEXT,
                key_path TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS MountPoints2 (
                user_name TEXT, mount_id TEXT, mount_type TEXT, key_path TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS RDPClientMRU (
                user_name TEXT, entry_type TEXT, server TEXT, username_hint TEXT,
                key_path TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS OfficeDocuments (
                user_name TEXT, application TEXT, version TEXT, kind TEXT,
                document TEXT, raw TEXT, key_path TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS FeatureUsage (
                user_name TEXT, usage_type TEXT, program TEXT, count INTEGER,
                key_path TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS CompatibilityAssistant (
                user_name TEXT, program_path TEXT, blob_size INTEGER,
                key_path TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS RecentApps (
                user_name TEXT, app_id TEXT, app_path TEXT, launch_count INTEGER,
                last_accessed TEXT, key_path TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS ApplicationArtifacts (
                user_name TEXT, application TEXT, artifact TEXT, name TEXT,
                value TEXT, key_path TEXT, parsed_at TEXT)''',
            # Per-user activity - same shape as the live parser.
            '''CREATE TABLE IF NOT EXISTS file_exts (
                user_name TEXT, extension TEXT, choice_type TEXT, progid TEXT,
                key_path TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS cid_size_mru (
                user_name TEXT, position INTEGER, application TEXT,
                key_path TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS programs_cache (
                user_name TEXT, value_name TEXT, blob_size INTEGER,
                key_path TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS regedit_lastkey (
                user_name TEXT, name TEXT, value TEXT, key_path TEXT,
                parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS printer_connections (
                user_name TEXT, connection TEXT, server TEXT, printer TEXT,
                key_path TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS explorer_advanced (
                user_name TEXT, setting TEXT, value TEXT, default_value TEXT,
                meaning TEXT, key_path TEXT, parsed_at TEXT)''',
            # Posture - one table per artifact, each carrying its stock default.
            '''CREATE TABLE IF NOT EXISTS rdp_tcp (
                setting TEXT, value TEXT, default_value TEXT, meaning TEXT,
                key_path TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS usbstor_start (
                setting TEXT, value TEXT, decoded TEXT, default_value TEXT,
                key_path TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS windows_script_host (
                setting TEXT, value TEXT, default_value TEXT, meaning TEXT,
                key_path TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS dnscache_parameters (
                name TEXT, value TEXT, key_path TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS files_not_to_snapshot (
                entry TEXT, value TEXT, key_path TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS winevt_channels (
                channel TEXT, source TEXT, enabled TEXT, max_size TEXT,
                retention TEXT, log_file TEXT, reason TEXT, key_path TEXT,
                parsed_at TEXT)''',
            # Device attribution.
            '''CREATE TABLE IF NOT EXISTS wpdbusenum (
                device_id TEXT, friendly_name TEXT, volume_guid TEXT,
                key_path TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS device_classes (
                class_guid TEXT, class_name TEXT, device_instance TEXT,
                key_path TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS volume_info_cache (
                drive_letter TEXT, volume_label TEXT, file_system TEXT,
                key_path TEXT, parsed_at TEXT)''',
            # Host identity.
            '''CREATE TABLE IF NOT EXISTS machine_guid (
                name TEXT, value TEXT, key_path TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS product_options (
                name TEXT, value TEXT, meaning TEXT, key_path TEXT,
                parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS os_install_history (
                name TEXT, value TEXT, key_path TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS active_computer_name (
                name TEXT, value TEXT, key_path TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS hivelist (
                hive TEXT, file_path TEXT, key_path TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS system_environment (
                name TEXT, value TEXT, key_path TEXT, parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS network_adapters (
                adapter_guid TEXT, name TEXT, value TEXT, key_path TEXT,
                parsed_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS group_policy_history (
                scope TEXT, gpo_id TEXT, name TEXT, value TEXT, key_path TEXT,
                parsed_at TEXT)'''):
            cursor.execute(_sql)

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
                return "; ".join(str(x) for x in v)
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
        _PRN = _cov_cs + r"\Control\Print\Printers"
        for s in _cov_subs(SY, _PRN):
            port, _p = _cov_one(SY, _PRN + "\\" + s, "Port")
            _cov_ins("ConnectedDevices",
                     ["device_type", "device_id", "friendly_name", "details",
                      "key_path", "parsed_at"],
                     ("Printer", s, s, "port: %s" % (port or ""), _PRN, _cov_stamp),
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
                         ["user_name", "setting", "value", "default_value",
                          "meaning", "key_path", "parsed_at"],
                         (_u, _n, str(_v), _dflt, _why, _EXA, _cov_stamp),
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
                     ["setting", "value", "default_value", "meaning", "key_path",
                      "parsed_at"],
                     (_n, str(_v), _dflt, _why, "SYSTEM\\" + _RDPT, _cov_stamp),
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
                     ["setting", "value", "default_value", "meaning", "key_path",
                      "parsed_at"],
                     (_n, str(_v), "(absent = enabled)", _why,
                      "SOFTWARE\\" + _WSH, _cov_stamp),
                     ["setting", "key_path"])

        _DNSP = _cov_cs + r"\Services\Dnscache\Parameters"
        for vn, vd, vt in _cov_vals(SY, _DNSP):
            _cov_ins("dnscache_parameters",
                     ["name", "value", "key_path", "parsed_at"],
                     (vn, _cov_fmt(vd)[:400], "SYSTEM\\" + _DNSP, _cov_stamp),
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
                     ["name", "value", "key_path", "parsed_at"],
                     (vn, _cov_fmt(vd)[:1000], "SYSTEM\\" + _SENV, _cov_stamp),
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

    # Return dictionary format expected by parser invoker
    return {
        'success': True,
        'records': total_records,
        'output_path': db_path
    }

if __name__ == "__main__":
    reg_Claw()

