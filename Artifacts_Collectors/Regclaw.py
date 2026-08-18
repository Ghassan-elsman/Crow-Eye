import sqlite3
try:
    import winreg
except ImportError:
    winreg = None
import os
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
        def reg_Claw_live(hive_key, key_path):
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
        def get_subkeys_live(hive_key, key_path):
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
            # Create tables if they don't exist (original tables for backward compatibility)
            tables = [
                ("machine_run", "name TEXT, row_data TEXT, type TEXT"),
                ("machine_run_once", "name TEXT, row_data TEXT, type TEXT"),
                ("user_run", "name TEXT, row_data TEXT, type TEXT"),
                ("user_run_once", "name TEXT, row_data TEXT, type TEXT"),
                ("Windows_lastupdate", "name TEXT, row_data TEXT, type TEXT"),
                ("Windows_lastupdate_subkeys", "subkey TEXT, name TEXT, row_data TEXT, type TEXT"),
                ("computer_Name", "name TEXT, row_data TEXT, type TEXT"),
                ("time_zone", "name TEXT, row_data TEXT, type TEXT"),
                ("network_interfaces", "subkey TEXT, name TEXT, row_data TEXT, type TEXT"),
                ("shutdown_information", "name TEXT, row_data TEXT, type TEXT")
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
        # Enhanced table for installed software
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
            execution_flags INTEGER,
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
            type TEXT,
            network_name TEXT,
            connection_date TEXT,
            gateway_mac TEXT,
            is_hidden INTEGER
        )''')
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
                        cursor.execute('INSERT OR IGNORE INTO AutoStartPrograms (location, program_name, command, parsed_at) VALUES (?, ?, ?, ?)',
                                      (location, name, str(data), format_forensic_timestamp(get_current_utc())))
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
            for name, (data, value_type) in values.items():
                try:
                    # Extract SID from subkey path
                    sid = subkey.split('\\')[-1] if '\\' in subkey else subkey
                   
                    # Initialize default values
                    process_path = ''
                    app_name = ''
                    last_execution = ''
                    execution_flags = 0
                   
                    # Use binary parser for REG_BINARY data
                    if value_type == 'REG_BINARY':
                        # Convert string to bytes if needed (Windows API sometimes returns strings)
                        binary_data = data if isinstance(data, bytes) else data.encode('latin-1') if isinstance(data, str) else data
                       
                        try:
                            parsed_data = registry_binary_parser.parse_bam_entry(name, binary_data)
                            process_path = parsed_data.get('process_path', name)
                            last_execution = parsed_data.get('last_execution', '')
                           
                            # Extract app name from process path
                            if process_path:
                                app_name = os.path.basename(process_path)
                        except Exception as parse_error:
                            logging.error(f"Error parsing BAM binary data for {subkey}/{name}: {parse_error}")
                            # Fallback to using the name as process path
                            process_path = name
                            app_name = os.path.basename(process_path) if process_path else ''
                    else:
                        # Non-binary data (like Version, SequenceNumber), skip or use name
                        process_path = name if name else str(data)
                        app_name = os.path.basename(process_path) if process_path else ''
                   
                    # Extract execution flags if present
                    if 'Flags' in values:
                        try:
                            execution_flags = int(values['Flags'][0])
                        except:
                            pass
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
                    cursor.execute('INSERT OR IGNORE INTO BAM (subkey, name, row_data, type, app_name, process_path, sid, last_execution, execution_flags, parsed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                                  (subkey, name, str(data), value_type, app_name, process_path, sid, last_execution, execution_flags, format_forensic_timestamp(get_current_utc())))
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
                                    
                                    # Convert focus time to readable format before saving
                                    focus_time_formatted = format_focus_time(focus_time_ms)
                                   
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
                        entries.append((full_path, value_name, data, mru_position,
                                        parent_readable))

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
            for registry_path, value_name, binary_data, mru_position, parent_path in entries:
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
                        logging.debug(f"Skipping duplicate Shellbags entry: {file_name}")
                        continue

                    # Note: mru_position is TEXT to support the "Unknown" value
                    cursor.execute('''INSERT INTO Shellbags
                                   (file_name, short_name, shell_item_type, mru_position,
                                    created_date, modified_date, accessed_date, attributes,
                                    file_size, special_folder, network_share, server_name, share_name,
                                    drive_letter, mft_record_number, registry_path, parent_path,
                                    parsed_at, user_name)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                                 (file_name, short_name, shell_item_type, mru_position,
                                  created_date, modified_date, accessed_date, attributes,
                                  file_size, special_folder, network_share, server_name, share_name,
                                  drive_letter, mft_record_number, registry_path, parent_path,
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
        network_list_paths = [
            "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\NetworkList\\Profiles",
            "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\NetworkList\\Signatures\\Unmanaged",
            "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\NetworkList\\Signatures\\Managed"
        ]
        
        for Netlist_reg_key in network_list_paths:
            try:
                logging.debug(f"Checking Network Lists path: {Netlist_reg_key}")
                Networklosts_subkeys = get_subkeys_live(HKEY_LOCAL_MACHINE, Netlist_reg_key)
                
                if Networklosts_subkeys:
                    logging.debug(f"Successfully read Network Lists from: {Netlist_reg_key}")
                
                # Insert data into the enhanced 'Network_list' table
                for subkey, values in Networklosts_subkeys.items():
                    network_name = ""
                    connection_date = ""
                    gateway_mac = ""
                    is_hidden = 0

                    # connection_date was only ever filled from a
                    # 'DateLastAccessTime' value, which these keys do not have -
                    # so the column was empty on all 52 rows while every profile
                    # carried DateCreated and DateLastConnected as 16-byte
                    # SYSTEMTIME. Read it up front so every row of this subkey
                    # carries the date, not just the ones written after the
                    # value happened to be reached.
                    for _dn, (_dd, _dt) in values.items():
                        if _dn.lower() == 'datelastconnected' and isinstance(_dd, bytes):
                            try:
                                _when = registry_binary_parser.parse_systemtime(_dd)
                                if _when:
                                    connection_date = _when
                            except Exception:
                                pass

                    # Extract network name
                    first_network_value = values.get('FirstNetwork', ('N/A', None))[0]
                    if first_network_value != 'N/A':
                        network_name = str(first_network_value)
                    
                    # Extract ProfileName if available (from Profiles path)
                    profile_name_value = values.get('ProfileName', ('N/A', None))[0]
                    if profile_name_value != 'N/A' and not network_name:
                        network_name = str(profile_name_value)
                    
                    # Extract other useful information
                    for name, (data, value_type) in values.items():
                        if name.lower() == 'profileguid':
                            # Try to get more info from the profile
                            try:
                                profile_path = f"SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\NetworkList\\Profiles\\{str(data)}"
                                profile_data = reg_Claw_live(HKEY_LOCAL_MACHINE, profile_path)
                                for profile_name, (profile_value, _) in profile_data.items():
                                    if profile_name.lower() == 'profilename' and not network_name:
                                        network_name = str(profile_value)
                                    elif profile_name.lower() == 'datelastaccesstime':
                                        try:
                                            # Convert Windows FILETIME to datetime
                                            dt = filetime_to_datetime(int(profile_value))
                                            connection_date = format_forensic_timestamp(dt)
                                        except:
                                            pass
                                    elif profile_name.lower() == 'nametype':
                                        try:
                                            # NameType 6 typically means hidden network
                                            is_hidden = 1 if int(profile_value) == 6 else 0
                                        except:
                                            pass
                            except Exception as e:
                                logging.debug(f"Error accessing profile {profile_path}: {e}")
                       
                        elif name.lower() == 'defaultgatewaymac':
                            # Format MAC address for readability
                            try:
                                if isinstance(data, bytes) and len(data) >= 6:
                                    gateway_mac = registry_binary_parser.format_mac_address(data)
                            except:
                                gateway_mac = str(data)
                        
                        # Parse binary timestamps if applicable
                        if name.lower() in ['datecreated', 'datelastconnected'] and isinstance(data, bytes) and len(data) >= 16:
                            try:
                                formatted_time = registry_binary_parser.parse_systemtime(data)
                                if formatted_time:
                                    data = formatted_time
                            except:
                                pass
                        
                        # Check if entry exists
                        if check_exists(cursor, 'Network_list', ['subkey', 'name', 'data', 'type'], (str(subkey), name, str(data), value_type)):
                            logging.debug(f"Skipping duplicate Network_list entry: {subkey}/{name}")
                            continue
                        
                        cursor.execute('INSERT OR IGNORE INTO Network_list (subkey, name, data, type, network_name, connection_date, gateway_mac, is_hidden) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                                      (str(subkey), name, str(data), value_type, network_name, connection_date, gateway_mac, is_hidden))
                
                logging.debug(f"Network list data from {Netlist_reg_key} inserted successfully")
            
            except Exception as e:
                logging.debug(f"Network Lists path unavailable: {Netlist_reg_key} - {e}")
        
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
                cursor.execute('INSERT OR IGNORE INTO Windows_lastupdate_subkeys (subkey, name, row_data, type) VALUES (?, ?, ?, ?)',
                              (str(subkey), name, str(data), value_type))
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
        for name, (data, value_type) in timezone_reg_key.items():
            if name.lower() == "timezonekeyname":
                tz_name = str(data)
            elif name.lower() == "standardname":
                standard_name = str(data)
            elif name.lower() == "daylightname":
                daylight_name = str(data)
            elif name.lower() == "bias":
                try:
                    bias = int(data)
                except:
                    bias = 0
            elif name.lower() == "activetimebias":
                try:
                    active_bias = int(data)
                except:
                    active_bias = 0
            if check_exists(cursor, 'time_zone', ['name', 'row_data', 'type'], (name, str(data), value_type)):
                logging.info(f"Skipping duplicate time_zone entry: {name}")
                continue
            cursor.execute('INSERT OR IGNORE INTO time_zone (name, row_data, type) VALUES (?, ?, ?)',
                          (name, str(data), value_type))
        # Insert into the enhanced table
        if not check_exists(cursor, 'TimeZoneInfo', ['time_zone_name', 'standard_name'], (tz_name, standard_name)):
            cursor.execute('''
            INSERT INTO TimeZoneInfo
            (time_zone_name, standard_name, daylight_name, bias, active_time_bias, parsed_at)
            VALUES (?, ?, ?, ?, ?, ?)''',
            (tz_name, standard_name, daylight_name, bias, active_bias, format_forensic_timestamp(get_current_utc())))
        else:
            logging.info("Skipping duplicate TimeZoneInfo entry")
        print("Time zone information inserted into database successfully.")
        # Network interfaces information - Enhanced version
        networkInterface_path = "SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters\\Interfaces"
        network_interfaces_sub_key = get_subkeys_live(HKEY_LOCAL_MACHINE, networkInterface_path)
        # Process each network interface
        for interface_id, values in network_interfaces_sub_key.items():
            ip_address = ""
            subnet_mask = ""
            default_gateway = ""
            dhcp_enabled = 0
            dhcp_server = ""
            dns_servers = ""
            mac_address = ""
            for name, (data, value_type) in values.items():
                if name.lower() == "ipaddress" or name.lower() == "dhcpipaddress":
                    ip_address = str(data)
                elif name.lower() == "subnetmask":
                    subnet_mask = str(data)
                elif name.lower() == "defaultgateway":
                    default_gateway = str(data)
                elif name.lower() == "enabledhcp":
                    try:
                        dhcp_enabled = int(data)
                    except:
                        dhcp_enabled = 0
                elif name.lower() == "dhcpserver":
                    dhcp_server = str(data)
                elif name.lower() == "nameserver":
                    dns_servers = str(data)
                elif name.lower() == "macaddress":
                    mac_address = str(data)
                # The static NameServer/DefaultGateway values exist on almost
                # every interface but are EMPTY on a DHCP client - the assigned
                # values live under the Dhcp* names. Reading only the static
                # ones left both columns blank on all 10 interfaces while two
                # of them really did have a DNS server and one a gateway. Only
                # fill from DHCP when the static value is empty, so a manually
                # configured address still wins.
                elif name.lower() == "dhcpnameserver":
                    if not dns_servers:
                        dns_servers = str(data)
                elif name.lower() == "dhcpdefaultgateway":
                    if not default_gateway:
                        default_gateway = ", ".join(str(x) for x in data)                             if isinstance(data, (list, tuple)) else str(data)
                # Keyed on (subkey, name) - one row per registry value, which is
                # what the offline parser has always done. With row_data in the
                # key, a value that legitimately changes between parses (the
                # DHCP lease times renew) was written again, so the table grew
                # on every re-parse of a live machine and never on an image.
                if check_exists(cursor, 'network_interfaces', ['subkey', 'name'], (str(interface_id), name)):
                    logging.info(f"Skipping duplicate network_interfaces entry: {interface_id}/{name}")
                    continue
                cursor.execute('INSERT OR IGNORE INTO network_interfaces (subkey, name, row_data, type) VALUES (?, ?, ?, ?)',
                              (str(interface_id), name, str(data), value_type))
            # Insert into the enhanced table
            if not check_exists(cursor, 'NetworkInterfacesInfo', ['interface_id', 'ip_address'], (interface_id, ip_address)):
                cursor.execute('''
                INSERT INTO NetworkInterfacesInfo
                (interface_id, ip_address, subnet_mask, default_gateway, dhcp_enabled, dhcp_server, dns_servers, mac_address, parsed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (interface_id, ip_address, subnet_mask, default_gateway, dhcp_enabled, dhcp_server, dns_servers, mac_address,
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
                shutdown_time = str(data)
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
            cursor.execute('INSERT OR IGNORE INTO shutdown_information (name, row_data, type) VALUES (?, ?, ?)',
                          (name, str(data), value_type))
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
                            if mru_position == 0 and most_recent_access:
                                # Most recent entry gets the key's last write time
                                # Mark it as such for forensic clarity
                                access_date = f"{most_recent_access} (Registry Key LastWrite)"
                            # For other entries, leave access_date empty
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
                    cursor.execute('INSERT INTO OpenSaveMRU (subkey, name, type, file_path, file_name, extension, drive_letter, access_date, row_data, parsed_at, user_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                                  (subkey, name, value_type, file_path, file_name, extension, drive_letter, access_date, str(data), format_forensic_timestamp(get_current_utc()), _live_user))
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
                
                # Determine access order/recency - use most_recent_access for most recent entry
                try:
                    entry_index = int(name)
                    if mru_order and entry_index in mru_order:
                        mru_position = mru_order.index(entry_index)
                        if mru_position == 0 and most_recent_access:
                            # Most recent entry gets the actual timestamp
                            access_date = most_recent_access
                        # For other entries, leave access_date empty instead of showing position
                except (ValueError, TypeError):
                    pass
               
                if check_exists(cursor, 'LastSaveMRU', ['mru_number', 'row_data', 'type'], (name, str(data), value_type)):
                    logging.info(f"Skipping duplicate LastSaveMRU entry: {name}")
                    continue
                cursor.execute('INSERT INTO LastSaveMRU (mru_number, type, application, folder_path, folder_name, drive_letter, access_date, row_data, parsed_at, user_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                              (name, value_type, application, folder_path, folder_name, drive_letter, access_date, str(data), format_forensic_timestamp(get_current_utc()), _live_user))
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
                    # Try to get connection times from the device properties
                    try:
                        device_props_path = f"SYSTEM\\CurrentControlSet\\Enum\\USBSTOR\\{device_class}\\{serial_number}\\Properties\\{{83da6326-97a6-4088-9453-a1923f573b29}}\\0065"
                        first_install = reg_Claw_live(HKEY_LOCAL_MACHINE, device_props_path)
                        if first_install:
                            for _, (data, _) in first_install.items():
                                try:
                                    # Convert Windows FILETIME to datetime
                                    filetime = int.from_bytes(data, byteorder='little')
                                    first_connected = format_forensic_timestamp(filetime_to_datetime(filetime))
                                except:
                                    first_connected = str(data)
                    except Exception as e:
                        logging.error(f"Error accessing USBSTOR first install time for {device_class}\\{serial_number}: {e}")
                    try:
                        device_props_path = f"SYSTEM\\CurrentControlSet\\Enum\\USBSTOR\\{device_class}\\{serial_number}\\Properties\\{{83da6326-97a6-4088-9453-a1923f573b29}}\\0067"
                        last_install = reg_Claw_live(HKEY_LOCAL_MACHINE, device_props_path)
                        if last_install:
                            for _, (data, _) in last_install.items():
                                try:
                                    # Convert Windows FILETIME to datetime
                                    filetime = int.from_bytes(data, byteorder='little')
                                    # Convert to datetime using centralized utility
                                    last_connected = format_forensic_timestamp(filetime_to_datetime(filetime))
                                except:
                                    last_connected = str(data)
                    except Exception as e:
                        logging.error(f"Error accessing USBSTOR last install time for {device_class}\\{serial_number}: {e}")
                    try:
                        device_props_path = f"SYSTEM\\CurrentControlSet\\Enum\\USBSTOR\\{device_class}\\{serial_number}\\Properties\\{{83da6326-97a6-4088-9453-a1923f573b29}}\\0066"
                        last_removal = reg_Claw_live(HKEY_LOCAL_MACHINE, device_props_path)
                        if last_removal:
                            for _, (data, _) in last_removal.items():
                                try:
                                    filetime = int.from_bytes(data, byteorder='little')
                                    # Convert to datetime using centralized utility
                                    last_removed = format_forensic_timestamp(filetime_to_datetime(filetime))
                                except:
                                    last_removed = str(data)
                    except Exception as e:
                        logging.error(f"Error accessing USBSTOR last removal time for {device_class}\\{serial_number}: {e}")
               
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
                # Only insert if there's a display name (filters out some system components)
                if display_name:
                    if check_exists(cursor, 'InstalledSoftware', ['display_name', 'display_version'], (display_name, display_version)):
                        logging.info(f"Skipping duplicate InstalledSoftware entry: {display_name}")
                        continue
                    cursor.execute('''
                    INSERT INTO InstalledSoftware
                    (display_name, display_version, publisher, install_date, install_location, uninstall_string, parsed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)''',
                    (display_name, display_version, publisher, install_date, install_location, uninstall_string,
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
                        (display_name, display_version, publisher, install_date, install_location, uninstall_string,
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
                    # Try to get last connected time
                    try:
                        device_props_path = f"SYSTEM\\CurrentControlSet\\Enum\\USB\\{device_id}\\{instance_id}\\Properties\\{{83da6326-97a6-4088-9453-a1923f573b29}}\\0067"
                        last_install = reg_Claw_live(HKEY_LOCAL_MACHINE, device_props_path)
                        if last_install:
                            for _, (data, _) in last_install.items():
                                try:
                                    # Convert Windows FILETIME to datetime
                                    filetime = int.from_bytes(data, byteorder='little')
                                    # Convert to datetime using centralized utility
                                    last_connected = format_forensic_timestamp(filetime_to_datetime(filetime))
                                except:
                                    last_connected = str(data)
                    except Exception as e:
                        logging.error(f"Error accessing USB last install time for {device_id}\\{instance_id}: {e}")
               
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
                            if name.lower() == "parent":
                                parent_id = str(data)
                            elif name.lower() == "service":
                                service = str(data)
                        # Determine status based on available information
                        if "removed" in instance_id.lower():
                            status = "Removed"
                        else:
                            status = "Present"
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
                    # Skip system profiles (those without S-1-5-21 prefix)
                    # S-1-5-21 prefix indicates domain/local user accounts
                    if not sid.startswith('S-1-5-21'):
                        continue
                    
                    # Extract profile information from ProfileList
                    profile_path = ""
                    profile_image_path = ""
                    profile_loaded = 0
                    
                    for name, (data, value_type) in profile_values.items():
                        if name.lower() == "profileimagepath":
                            profile_image_path = str(data)
                            # Extract just the profile directory name (username)
                            if '\\' in profile_image_path:
                                profile_path = profile_image_path.split('\\')[-1]
                        elif name.lower() == "state":
                            # State 0 = loaded, 256 = unloaded
                            try:
                                state = int(data)
                                profile_loaded = 1 if state == 0 else 0
                            except:
                                pass
                    
                    # Use profile directory name as username
                    username = profile_path if profile_path else "Unknown"
                    
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
                                   (location, program_name, command, parsed_at)
                                   VALUES (?, ?, ?, ?)''',
                                ("TaskCache" + task_path, task_path.rsplit("\\", 1)[-1], full, stamp))
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
                    'hive TEXT, key_path TEXT, name TEXT, data TEXT, type TEXT, '
                    'user_name TEXT, parsed_at TEXT)')

            def _type_name(t):
                return {winreg.REG_SZ: "REG_SZ", winreg.REG_EXPAND_SZ: "REG_EXPAND_SZ",
                        winreg.REG_MULTI_SZ: "REG_MULTI_SZ", winreg.REG_DWORD: "REG_DWORD",
                        winreg.REG_QWORD: "REG_QWORD", winreg.REG_BINARY: "REG_BINARY",
                        winreg.REG_NONE: "REG_NONE"}.get(t, f"REG_TYPE_{t}")

            def _fmt(data):
                # REG_MULTI_SZ arrives as a Python list. Storing repr() would put
                # "['msv1_0', 'SshdPinAuthLsa']" in the cell; join it instead so the
                # column stays greppable. reg.exe shows the same value NUL-separated.
                if isinstance(data, list):
                    return "; ".join(str(x) for x in data)
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
                            for n in names:
                                try:
                                    d, t = winreg.QueryValueEx(k, n)
                                    out.append((n, d, t))
                                except FileNotFoundError:
                                    pass
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
                    cursor.execute(
                        f'INSERT INTO {table} (hive, key_path, name, data, type, '
                        'user_name, parsed_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                        (hive, key_path, name, value, _type_name(rtype),
                         _owner, persist_stamp))
                    asep_count += 1
                if roll_up and value:
                    loc = roll_up if not user_name else f"HKU\\{user_name} {roll_up}"
                    if not check_exists(cursor, 'AutoStartPrograms',
                                        ['location', 'program_name'], (loc, name)):
                        cursor.execute(
                            'INSERT INTO AutoStartPrograms '
                            '(location, program_name, command, parsed_at) '
                            'VALUES (?, ?, ?, ?)', (loc, name, value, persist_stamp))

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

            # ---------------------------------------------------------- posture
            cursor.execute('''CREATE TABLE IF NOT EXISTS SecurityPosture (
                setting TEXT, value_raw TEXT, value_decoded TEXT,
                default_value TEXT, assessment TEXT, meaning TEXT,
                key_path TEXT, parsed_at TEXT)''')

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
                key_path TEXT, parsed_at TEXT)''')
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
                key_path TEXT, parsed_at TEXT)''')
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
                key_path TEXT, parsed_at TEXT)''')
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

            # ------------------------------------------------- per-user artifacts
            # Collected for EVERY loaded user, not just the account running
            # Crow-Eye. HKU\<SID>\... returns the same data HKCU does for the
            # current user, so one loop covers both.
            _cu_sid2 = get_current_user_sid()
            _cu_name = get_username_from_sid(_cu_sid2) if _cu_sid2 else None
            user_roots = [(HKCU_R, "", _cu_name or "current user")]
            try:
                SERVICE = {"S-1-5-18", "S-1-5-19", "S-1-5-20"}
                with winreg.OpenKey(winreg.HKEY_USERS, "", 0, RD64) as _uk:
                    for _i in range(winreg.QueryInfoKey(_uk)[0]):
                        _s = winreg.EnumKey(_uk, _i)
                        if (_s.startswith("S-1-5-21") and not _s.endswith("_Classes")
                                and _s not in SERVICE and _s != _cu_sid2):
                            user_roots.append((winreg.HKEY_USERS, _s + "\\", _s))
            except OSError as e:
                logging.debug("HKEY_USERS walk for coverage: %s", e)

            cursor.execute('''CREATE TABLE IF NOT EXISTS MountPoints2 (
                user_name TEXT, mount_id TEXT, mount_type TEXT, key_path TEXT,
                parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS RDPClientMRU (
                user_name TEXT, entry_type TEXT, server TEXT, username_hint TEXT,
                key_path TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS OfficeDocuments (
                user_name TEXT, application TEXT, version TEXT, kind TEXT,
                document TEXT, raw TEXT, key_path TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS FeatureUsage (
                user_name TEXT, usage_type TEXT, program TEXT, count INTEGER,
                key_path TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS CompatibilityAssistant (
                user_name TEXT, program_path TEXT, blob_size INTEGER,
                key_path TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS RecentApps (
                user_name TEXT, app_id TEXT, app_path TEXT, launch_count INTEGER,
                last_accessed TEXT, key_path TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS ApplicationArtifacts (
                user_name TEXT, application TEXT, artifact TEXT, name TEXT,
                value TEXT, key_path TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS file_exts (
                user_name TEXT, extension TEXT, choice_type TEXT, progid TEXT,
                key_path TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS cid_size_mru (
                user_name TEXT, position INTEGER, application TEXT,
                key_path TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS programs_cache (
                user_name TEXT, value_name TEXT, blob_size INTEGER,
                key_path TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS regedit_lastkey (
                user_name TEXT, name TEXT, value TEXT, key_path TEXT,
                parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS printer_connections (
                user_name TEXT, connection TEXT, server TEXT, printer TEXT,
                key_path TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS explorer_advanced (
                user_name TEXT, setting TEXT, value TEXT, default_value TEXT,
                meaning TEXT, key_path TEXT, parsed_at TEXT)''')

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
                         ["user_name", "setting", "value", "default_value",
                          "meaning", "key_path", "parsed_at"],
                         (_uname, _n, str(_v), _dflt, _why, EXA, cov_stamp),
                         ["user_name", "setting"])

            # ----------------------------------------------------- posture keys
            # One table per artifact, each carrying its own stock default so a
            # deviation is readable without a second source. These are separate
            # from SecurityPosture because each is a distinct key an examiner
            # queries by name, not another row in a settings bag.
            cursor.execute('''CREATE TABLE IF NOT EXISTS rdp_tcp (
                setting TEXT, value TEXT, default_value TEXT, meaning TEXT,
                key_path TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS usbstor_start (
                setting TEXT, value TEXT, decoded TEXT, default_value TEXT,
                key_path TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS windows_script_host (
                setting TEXT, value TEXT, default_value TEXT, meaning TEXT,
                key_path TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS dnscache_parameters (
                name TEXT, value TEXT, key_path TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS files_not_to_snapshot (
                entry TEXT, value TEXT, key_path TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS winevt_channels (
                channel TEXT, source TEXT, enabled TEXT, max_size TEXT,
                retention TEXT, log_file TEXT, reason TEXT, key_path TEXT,
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
                     ["setting", "value", "default_value", "meaning", "key_path",
                      "parsed_at"],
                     (_n, str(_v), _dflt, _why, RDPT, cov_stamp),
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
                     ["setting", "value", "default_value", "meaning", "key_path",
                      "parsed_at"],
                     (_n, str(_v), "(absent = enabled)", _why, WSH, cov_stamp),
                     ["setting", "key_path"])

            DNSP = r"SYSTEM\CurrentControlSet\Services\Dnscache\Parameters"
            for _vn, _vd, _vt in _cvals(HKLM_R, DNSP):
                _ins("dnscache_parameters",
                     ["name", "value", "key_path", "parsed_at"],
                     (_vn, _fmt(_vd)[:400], DNSP, cov_stamp),
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
                key_path TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS device_classes (
                class_guid TEXT, class_name TEXT, device_instance TEXT,
                key_path TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS volume_info_cache (
                drive_letter TEXT, volume_label TEXT, file_system TEXT,
                key_path TEXT, parsed_at TEXT)''')

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
                name TEXT, value TEXT, key_path TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS product_options (
                name TEXT, value TEXT, meaning TEXT, key_path TEXT,
                parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS os_install_history (
                name TEXT, value TEXT, key_path TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS active_computer_name (
                name TEXT, value TEXT, key_path TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS hivelist (
                hive TEXT, file_path TEXT, key_path TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS system_environment (
                name TEXT, value TEXT, key_path TEXT, parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS network_adapters (
                adapter_guid TEXT, name TEXT, value TEXT, key_path TEXT,
                parsed_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS group_policy_history (
                scope TEXT, gpo_id TEXT, name TEXT, value TEXT, key_path TEXT,
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
                     ["name", "value", "key_path", "parsed_at"],
                     (_vn, _fmt(_vd)[:1000], SENV, cov_stamp), ["name"])

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

            # S-1-5-18/19/20 are LocalSystem / LocalService / NetworkService.
            SERVICE_SIDS = {"S-1-5-18", "S-1-5-19", "S-1-5-20"}

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
            for _t in ("RunMRU", "WordWheelQuery"):
                cursor.execute(f"PRAGMA table_info({_t})")
                _cols = [c[1] for c in cursor.fetchall()]
                if _cols and "key_last_write" not in _cols:
                    cursor.execute(
                        f"ALTER TABLE {_t} ADD COLUMN key_last_write TEXT")

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

            other_sids = [s for s in loaded
                          if s.startswith("S-1-5-21")
                          and not s.endswith("_Classes")
                          and s not in SERVICE_SIDS
                          and s != _cu_sid]

            other_rows = 0
            for sid in other_sids:
                uname = sid_names.get(sid) or sid
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
                                '(location, program_name, command, parsed_at) '
                                'VALUES (?, ?, ?, ?)', (loc, nm, str(dt), user_stamp))
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
                uname = sid_names.get(sid) or sid
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
                        cursor.execute(
                            'INSERT INTO ' + table + ' (hive, key_path, name, '
                            'data, type, user_name, parsed_at) '
                            'VALUES (?, ?, ?, ?, ?, ?, ?)',
                            ("HKCU", _kp, _nm, _val, _u_type(_ty), uname, user_stamp))
                        written += 1
                    if roll and _val:
                        _loc = "HKU\\" + uname + " " + roll
                        if not check_exists(cursor, 'AutoStartPrograms',
                                            ['location', 'program_name'],
                                            (_loc, _nm)):
                            cursor.execute(
                                'INSERT INTO AutoStartPrograms '
                                '(location, program_name, command, parsed_at) '
                                'VALUES (?, ?, ?, ?)',
                                (_loc, _nm, _val, user_stamp))
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
