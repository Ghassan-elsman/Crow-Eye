import sqlite3
import winreg
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
    if platform.system() != "Windows":
        return False
    return bool(ctypes.windll.shell32.IsUserAnAdmin())

def require_admin_privileges():
    """Require administrative privileges or exit.
    
    This function should be called by operations that absolutely require admin access.
    For operations that can work with degraded functionality, use check_admin_privileges() instead.
    """
    if platform.system() != "Windows":
        print("Error: This script is designed for Windows systems only.")
        exit(1)
    if not ctypes.windll.shell32.IsUserAnAdmin():
        print("Error: This script requires administrative privileges.")
        print("Please run as Administrator to access all registry data.")
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
        query = f"SELECT 1 FROM {table_name} WHERE {' AND '.join(f'{col} = ?' for col in conditions)}"
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
                        logging.error(f"Error reading subkey {subkey_path}: {e}")
            return subkey_values
        except Exception as e:
            logging.error(f"Error reading subkeys for {key_path}: {e}")
            return {}
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
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    # Connect to SQLite database (or create it if it doesn't exist)
    with sqlite3.connect(db_filename) as conn:
        cursor = conn.cursor()
        # Create tables if they don't exist (original tables for backward compatibility)
        tables = [
            ("machine_run", "name TEXT, data TEXT, type TEXT"),
            ("machine_run_once", "name TEXT, data TEXT, type TEXT"),
            ("user_run", "name TEXT, data TEXT, type TEXT"),
            ("user_run_once", "name TEXT, data TEXT, type TEXT"),
            ("Windows_lastupdate", "name TEXT, data TEXT, type TEXT"),
            ("Windows_lastupdate_subkeys", "subkey TEXT, name TEXT, data TEXT, type TEXT"),
            ("computer_Name", "name TEXT, data TEXT, type TEXT"),
            ("time_zone", "name TEXT, data TEXT, type TEXT"),
            ("network_interfaces", "subkey TEXT, name TEXT, data TEXT, type TEXT"),
            ("shutdown_information", "name TEXT, data TEXT, type TEXT")
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
            timestamp TEXT
        )''')
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS TimeZoneInfo (
            time_zone_name TEXT,
            standard_name TEXT,
            daylight_name TEXT,
            bias INTEGER,
            active_time_bias INTEGER,
            timestamp TEXT
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
            timestamp TEXT
        )''')
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS Auto (
            last_install_time TEXT,
            au_options INTEGER,
            scheduled_install_day INTEGER,
            scheduled_install_time INTEGER,
            timestamp TEXT
        )''')
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS WindowsUpdateInfo (
            last_check_time TEXT,
            last_install_time TEXT,
            au_options INTEGER,
            scheduled_install_day INTEGER,
            scheduled_install_time INTEGER,
            timestamp TEXT
        )''')
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS ShutdownInfo (
            shutdown_time TEXT,
            shutdown_count INTEGER,
            shutdown_type TEXT,
            clean_shutdown INTEGER,
            timestamp TEXT
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
            timestamp TEXT
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
            timestamp TEXT,
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
            timestamp TEXT
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
            timestamp TEXT
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
            timestamp TEXT
        )''')
        # Create table for auto start programs
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS AutoStartPrograms (
            location TEXT,
            program_name TEXT,
            command TEXT,
            timestamp TEXT,
            PRIMARY KEY (location, program_name)
        )''')
        # Enhanced DAM and BAM tables with detailed process information
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS DAM (
            subkey TEXT,
            name TEXT,
            data TEXT,
            type TEXT,
            app_name TEXT,
            process_path TEXT,
            sid TEXT,
            last_execution TEXT,
            execution_count INTEGER,
            timestamp TEXT
        )''')
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS BAM (
            subkey TEXT,
            name TEXT,
            data TEXT,
            type TEXT,
            app_name TEXT,
            process_path TEXT,
            sid TEXT,
            last_execution TEXT,
            execution_flags INTEGER,
            timestamp TEXT
        )''')
        # WordWheelQuery table for Windows Explorer search history
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS WordWheelQuery (
            search_term TEXT,
            search_type TEXT,
            mru_position INTEGER,
            access_date TEXT,
            timestamp TEXT
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
            timestamp TEXT
        )''')
        # Shellbags table for folder access history (enhanced with additional metadata)
        # Check if old schema exists and migrate if needed
        cursor.execute("PRAGMA table_info(Shellbags)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if columns and 'timestamp' in columns and 'analyzing_date' not in columns:
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
                analyzing_date TEXT
            )''')
            
            # Copy existing data (folder_name becomes file_name, mru_position becomes TEXT)
            cursor.execute('''INSERT INTO Shellbags_new 
                (file_name, shell_item_type, mru_position, 
                 created_date, modified_date, accessed_date, attributes, 
                 file_size, special_folder, network_share, registry_path, analyzing_date)
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
                analyzing_date TEXT
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
            timestamp TEXT
        )''')
        # MUICache table for application name and path tracking
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS MUICache (
            app_path TEXT,
            app_name TEXT,
            file_extension TEXT,
            timestamp TEXT
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
            data TEXT,
            analyzing_date TEXT
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
            data TEXT,
            analyzing_date TEXT
        )''')
        # User Profiles table for user account information from ProfileList
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS UserProfiles (
            user_sid TEXT PRIMARY KEY,
            username TEXT,
            profile_path TEXT,
            profile_image_path TEXT,
            profile_loaded INTEGER,
            timestamp TEXT
        )''')
        # Insert data into the respective tables
        for table_name, (hive, key) in paths.items():
            output = reg_Claw_live(hive, key)
            db_table_name = table_name_mapping.get(table_name, table_name)
            for name, (data, value_type) in output.items():
                try:
                    # Check if entry exists for tables without primary keys
                    if db_table_name in ['machine_run', 'machine_run_once', 'user_run', 'user_run_once', 'DAM', 'BAM']:
                        if check_exists(cursor, db_table_name, ['name', 'data', 'type'], (name, str(data), value_type)):
                            logging.info(f"Skipping duplicate entry in {db_table_name}: {name}")
                            continue
                    cursor.execute(f'INSERT OR IGNORE INTO {db_table_name} (name, data, type) VALUES (?, ?, ?)',
                                  (name, str(data), value_type))
                    # Also insert into the AutoStartPrograms table
                    if table_name in ["machine_run", "machine_run_once", "user_run", "user_run_once"]:
                        location = {
                            "machine_run": "HKLM Run",
                            "machine_run_once": "HKLM RunOnce",
                            "user_run": "HKCU Run",
                            "user_run_once": "HKCU RunOnce"
                        }[table_name]
                        cursor.execute('INSERT OR IGNORE INTO AutoStartPrograms (location, program_name, command, timestamp) VALUES (?, ?, ?, ?)',
                                      (location, name, str(data), datetime.datetime.now().isoformat()))
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
                            dt = datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=filetime/10)
                            last_execution = dt.isoformat()
                        except:
                            pass
                    if 'AccessCount' in values:
                        try:
                            execution_count = int(values['AccessCount'][0])
                        except:
                            pass
                    # Check if entry exists
                    if check_exists(cursor, 'DAM', ['subkey', 'name', 'data', 'type'], (subkey, name, str(data), value_type)):
                        logging.info(f"Skipping duplicate DAM entry: {subkey}/{name}")
                        continue
                    cursor.execute('INSERT OR IGNORE INTO DAM (subkey, name, data, type, app_name, process_path, sid, last_execution, execution_count, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                                  (subkey, name, str(data), value_type, app_name, process_path, sid, last_execution, execution_count, datetime.datetime.now().isoformat()))
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
                    # Check if entry exists
                    if check_exists(cursor, 'BAM', ['subkey', 'name', 'data', 'type'], (subkey, name, str(data), value_type)):
                        logging.info(f"Skipping duplicate BAM entry: {subkey}/{name}")
                        continue
                    cursor.execute('INSERT OR IGNORE INTO BAM (subkey, name, data, type, app_name, process_path, sid, last_execution, execution_flags, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                                  (subkey, name, str(data), value_type, app_name, process_path, sid, last_execution, execution_flags, datetime.datetime.now().isoformat()))
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
                                   
                                    # Check if entry exists
                                    if check_exists(cursor, 'UserAssist', ['program_path', 'user_sid'], (program_path, user_sid)):
                                        logging.info(f"Skipping duplicate UserAssist entry: {program_path}")
                                        continue
                                   
                                    # Insert into database with formatted focus time
                                    cursor.execute('''INSERT OR IGNORE INTO UserAssist
                                                   (program_path, run_count, last_execution, focus_count, focus_time, user_sid, timestamp)
                                                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                                                 (program_path, run_count, last_execution, focus_count, focus_time_formatted,
                                                  user_sid, datetime.datetime.now().isoformat()))
                                    
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
       
        def enumerate_shellbags_recursive(hive_key, base_path, current_path="", depth=0, max_depth=20):
            """
            Recursively enumerate Shellbags keys to capture nested folder structures.
           
            Args:
                hive_key: Registry hive (HKEY_CURRENT_USER)
                base_path: Base registry path for Shellbags
                current_path: Current subkey path (for recursion)
                depth: Current recursion depth
                max_depth: Maximum recursion depth to prevent infinite loops
           
            Returns:
                List of tuples: (registry_path, value_name, binary_data, mru_position)
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
                        entries.append((full_path, value_name, data, mru_position))
               
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
                               
                                # Recursively process subkey
                                subkey_path = f"{current_path}\\{subkey_name}" if current_path else subkey_name
                                sub_entries = enumerate_shellbags_recursive(hive_key, base_path, subkey_path, depth + 1, max_depth)
                                entries.extend(sub_entries)
                            except Exception as e:
                                logging.error(f"Error enumerating Shellbags subkey {i} in {full_path}: {e}")
                                continue
                except Exception as e:
                    logging.error(f"Error accessing Shellbags subkeys for {full_path}: {e}")
           
            except Exception as e:
                logging.error(f"Error accessing Shellbags key {full_path}: {e}")
           
            return entries
       
        try:
            shellbags_count = 0
           
            # Enumerate Shellbags from all registry paths
            for shellbags_path in shellbags_paths:
                try:
                    logging.info(f"Enumerating Shellbags from {shellbags_path}")
                   
                    # Recursively enumerate all Shellbags entries
                    entries = enumerate_shellbags_recursive(HKEY_CURRENT_USER, shellbags_path)
                   
                    # Process each entry
                    for registry_path, value_name, binary_data, mru_position in entries:
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
                           
                            # Check if entry exists (using file_name and registry_path)
                            if check_exists(cursor, 'Shellbags', ['file_name', 'registry_path'], (file_name, registry_path)):
                                logging.debug(f"Skipping duplicate Shellbags entry: {file_name}")
                                continue
                           
                            # Insert into database with enhanced metadata
                            # Note: mru_position is now TEXT type to support "Unknown" value
                            cursor.execute('''INSERT OR IGNORE INTO Shellbags
                                           (file_name, short_name, shell_item_type, mru_position, 
                                            created_date, modified_date, accessed_date, attributes,
                                            file_size, special_folder, network_share, server_name, share_name,
                                            drive_letter, mft_record_number, registry_path, analyzing_date)
                                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                                         (file_name, short_name, shell_item_type, mru_position, 
                                          created_date, modified_date, accessed_date, attributes,
                                          file_size, special_folder, network_share, server_name, share_name,
                                          drive_letter, mft_record_number, registry_path, 
                                          datetime.datetime.now().isoformat()))
                           
                            shellbags_count += 1
                            logging.debug(f"Shellbag {value_name} MRU position: {mru_position}")
                           
                        except Exception as e:
                            logging.error(f"Error parsing Shellbags entry {registry_path}/{value_name}: {e}")
                            import traceback
                            logging.debug(traceback.format_exc())
                            continue
               
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
                    if check_exists(cursor, 'RunMRU', ['command', 'mru_position'], (command, mru_position)):
                        logging.info(f"Skipping duplicate RunMRU entry: {command}")
                        continue
                   
                    # Insert into database
                    cursor.execute('''INSERT OR IGNORE INTO RunMRU
                                   (command, mru_position, access_date, timestamp)
                                   VALUES (?, ?, ?, ?)''',
                                 (command, mru_position, access_date, datetime.datetime.now().isoformat()))
                   
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
                        app_name = parsed_data.get('app_name', '')
                        file_extension = parsed_data.get('file_extension', '')
                       
                        # Skip if no path extracted
                        if not app_path:
                            logging.debug(f"Skipping MUICache entry with no path: {value_name}")
                            continue
                       
                        # Check if entry exists
                        if check_exists(cursor, 'MUICache', ['app_path'], (app_path,)):
                            logging.info(f"Skipping duplicate MUICache entry: {app_path}")
                            continue
                       
                        # Insert into database
                        cursor.execute('''INSERT OR IGNORE INTO MUICache
                                       (app_path, app_name, file_extension, timestamp)
                                       VALUES (?, ?, ?, ?)''',
                                     (app_path, app_name, file_extension, datetime.datetime.now().isoformat()))
                       
                        muicache_count += 1
                       
                    except Exception as e:
                        logging.error(f"Error parsing MUICache entry {value_name}: {e}")
                        continue
               
            except Exception as e:
                logging.debug(f"MUICache path not accessible: {muicache_path} - {e}")
                continue
       
        print(f"MUICache data inserted into database successfully. Total entries: {muicache_count}")
        # WordWheelQuery collection - Windows Explorer search history
        wordwheelquery_count = 0
        wordwheelquery_path = "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\WordWheelQuery"
       
        try:
            wordwheelquery_data = reg_Claw_live(HKEY_CURRENT_USER, wordwheelquery_path)
           
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
                        cursor.execute('''INSERT OR IGNORE INTO WordWheelQuery
                                       (search_term, search_type, mru_position, access_date, timestamp)
                                       VALUES (?, ?, ?, ?, ?)''',
                                     (search_term, search_type, mru_position, access_date,
                                      datetime.datetime.now().isoformat()))
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
        Netlist_reg_key = "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\NetworkList\\Signatures\\Unmanaged"
        Networklosts_subkeys = get_subkeys_live(HKEY_LOCAL_MACHINE, Netlist_reg_key)
        # Insert data into the enhanced 'Network_list' table
        for subkey, values in Networklosts_subkeys.items():
            network_name = ""
            connection_date = ""
            gateway_mac = ""
            is_hidden = 0
            # Extract network name
            first_network_value = values.get('FirstNetwork', ('N/A', None))[0]
            if first_network_value != 'N/A':
                network_name = str(first_network_value)
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
                                    filetime = int(profile_value)
                                    dt = datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=filetime/10)
                                    connection_date = dt.isoformat()
                                except:
                                    pass
                            elif profile_name.lower() == 'nametype':
                                try:
                                    # NameType 6 typically means hidden network
                                    is_hidden = 1 if int(profile_value) == 6 else 0
                                except:
                                    pass
                    except Exception as e:
                        logging.error(f"Error accessing profile {profile_path}: {e}")
               
                elif name.lower() == 'defaultgatewaymacc':
                    # Format MAC address for readability
                    try:
                        if isinstance(data, bytes) and len(data) >= 6:
                            mac_bytes = data[:6]
                            gateway_mac = ':'.join(f'{b:02x}' for b in mac_bytes)
                    except:
                        gateway_mac = str(data)
                # Check if entry exists
                if check_exists(cursor, 'Network_list', ['subkey', 'name', 'data', 'type'], (str(subkey), name, str(data), value_type)):
                    logging.info(f"Skipping duplicate Network_list entry: {subkey}/{name}")
                    continue
                cursor.execute('INSERT OR IGNORE INTO Network_list (subkey, name, data, type, network_name, connection_date, gateway_mac, is_hidden) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                              (str(subkey), name, str(data), value_type, network_name, connection_date, gateway_mac, is_hidden))
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
            if check_exists(cursor, 'Windows_lastupdate', ['name', 'data', 'type'], (name, str(data), _)):
                logging.info(f"Skipping duplicate Windows_lastupdate entry: {name}")
                continue
            cursor.execute('INSERT OR IGNORE INTO Windows_lastupdate (name, data, type) VALUES (?, ?, ?)',
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
            (last_check_time, last_install_time, au_options, scheduled_install_day, scheduled_install_time, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)''',
            (last_check, last_install, au_options, scheduled_day, scheduled_time, datetime.datetime.now().isoformat()))
        else:
            logging.info("Skipping duplicate WindowsUpdateInfo entry")
        # Insert subkeys data
        for subkey, values in last_update_subkey.items():
            for name, (data, value_type) in values.items():
                if check_exists(cursor, 'Windows_lastupdate_subkeys', ['subkey', 'name', 'data', 'type'], (str(subkey), name, str(data), value_type)):
                    logging.info(f"Skipping duplicate Windows_lastupdate_subkeys entry: {subkey}/{name}")
                    continue
                cursor.execute('INSERT OR IGNORE INTO Windows_lastupdate_subkeys (subkey, name, data, type) VALUES (?, ?, ?, ?)',
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
        product_id = ""
        install_date = ""
        for name, (data, _) in ComputerName_reg_key.items():
            if name.lower() == "computername":
                computer_name = str(data)
            if check_exists(cursor, 'computer_Name', ['name', 'data', 'type'], (name, str(data), _)):
                logging.info(f"Skipping duplicate computer_Name entry: {name}")
                continue
            cursor.execute('INSERT OR IGNORE INTO computer_Name (name, data, type) VALUES (?, ?, ?)',
                          (name, str(data), _))
        # Extract system info
        for name, (data, _) in system_info.items():
            if name.lower() == "registeredowner":
                registered_owner = str(data)
            elif name.lower() == "registeredorganization":
                registered_org = str(data)
            elif name.lower() == "productid":
                product_id = str(data)
            elif name.lower() == "installdate":
                try:
                    # Convert Windows timestamp to readable date
                    install_date = datetime.datetime.fromtimestamp(int(data)).isoformat()
                except:
                    install_date = str(data)
        # Insert into the enhanced table
        if not check_exists(cursor, 'ComputerNameInfo', ['computer_name', 'registered_owner'], (computer_name, registered_owner)):
            cursor.execute('''
            INSERT INTO ComputerNameInfo
            (computer_name, registered_owner, registered_organization, product_id, installation_date, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)''',
            (computer_name, registered_owner, registered_org, product_id, install_date, datetime.datetime.now().isoformat()))
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
            if check_exists(cursor, 'time_zone', ['name', 'data', 'type'], (name, str(data), value_type)):
                logging.info(f"Skipping duplicate time_zone entry: {name}")
                continue
            cursor.execute('INSERT OR IGNORE INTO time_zone (name, data, type) VALUES (?, ?, ?)',
                          (name, str(data), value_type))
        # Insert into the enhanced table
        if not check_exists(cursor, 'TimeZoneInfo', ['time_zone_name', 'standard_name'], (tz_name, standard_name)):
            cursor.execute('''
            INSERT INTO TimeZoneInfo
            (time_zone_name, standard_name, daylight_name, bias, active_time_bias, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)''',
            (tz_name, standard_name, daylight_name, bias, active_bias, datetime.datetime.now().isoformat()))
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
                if check_exists(cursor, 'network_interfaces', ['subkey', 'name', 'data', 'type'], (str(interface_id), name, str(data), value_type)):
                    logging.info(f"Skipping duplicate network_interfaces entry: {interface_id}/{name}")
                    continue
                cursor.execute('INSERT OR IGNORE INTO network_interfaces (subkey, name, data, type) VALUES (?, ?, ?, ?)',
                              (str(interface_id), name, str(data), value_type))
            # Insert into the enhanced table
            if not check_exists(cursor, 'NetworkInterfacesInfo', ['interface_id', 'ip_address'], (interface_id, ip_address)):
                cursor.execute('''
                INSERT INTO NetworkInterfacesInfo
                (interface_id, ip_address, subnet_mask, default_gateway, dhcp_enabled, dhcp_server, dns_servers, mac_address, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (interface_id, ip_address, subnet_mask, default_gateway, dhcp_enabled, dhcp_server, dns_servers, mac_address,
                 datetime.datetime.now().isoformat()))
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
            if check_exists(cursor, 'shutdown_information', ['name', 'data', 'type'], (name, str(data), value_type)):
                logging.info(f"Skipping duplicate shutdown_information entry: {name}")
                continue
            cursor.execute('INSERT OR IGNORE INTO shutdown_information (name, data, type) VALUES (?, ?, ?)',
                          (name, str(data), value_type))
        for name, (data, _) in shutdown_time_key.items():
            if name.lower() == "lastpoweroff":
                try:
                    # Convert Windows timestamp to readable date if possible
                    shutdown_time = datetime.datetime.fromtimestamp(int(data)).isoformat()
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
            (shutdown_time, shutdown_count, shutdown_type, clean_shutdown, timestamp)
            VALUES (?, ?, ?, ?, ?)''',
            (shutdown_time, shutdown_count, shutdown_type, clean_shutdown, datetime.datetime.now().isoformat()))
        else:
            logging.info("Skipping duplicate ShutdownInfo entry")
        print('Shutdown information inserted into database successfully.')
        # Recent opened docs
        recent_docs_path = "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\RecentDocs"
        # Create a single table for RecentDocs key and subkeys
        cursor.execute('CREATE TABLE IF NOT EXISTS RecentDocs (subkey TEXT, name TEXT, data TEXT, type TEXT)')
        # Read and insert data from RecentDocs key
        recent_docs_key = reg_Claw_live(HKEY_CURRENT_USER, recent_docs_path)
        for name, (data, value_type) in recent_docs_key.items():
            # Parse binary data to extract clean filename
            if value_type == 'REG_BINARY' and isinstance(data, bytes):
                try:
                    # Use the specialized RecentDocs parser
                    parsed_filename = registry_binary_parser.parse_recentdocs_entry(data)
                   
                    # If parsing failed or returned empty, fall back to string representation
                    if not parsed_filename:
                        parsed_filename = str(data)
                        logging.warning(f"RecentDocs parser returned empty for main key/{name}, using fallback")
                except Exception as e:
                    logging.error(f"Error parsing RecentDocs entry for main key/{name}: {e}")
                    parsed_filename = str(data)
            else:
                # For non-binary data, use string representation
                parsed_filename = str(data)
           
            if check_exists(cursor, 'RecentDocs', ['subkey', 'name', 'data', 'type'], ('main key', name, parsed_filename, value_type)):
                logging.info(f"Skipping duplicate RecentDocs entry: main key/{name}")
                continue
            cursor.execute('INSERT OR IGNORE INTO RecentDocs (subkey, name, data, type) VALUES (?, ?, ?, ?)',
                          ('main key', name, parsed_filename, value_type))
        # Read and insert data from RecentDocs subkeys
        recent_docs_subkeys = get_subkeys_live(HKEY_CURRENT_USER, recent_docs_path)
        for subkey, values in recent_docs_subkeys.items():
            for name, (data, value_type) in values.items():
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
               
                if check_exists(cursor, 'RecentDocs', ['subkey', 'name', 'data', 'type'], (subkey, name, parsed_filename, value_type)):
                    logging.info(f"Skipping duplicate RecentDocs entry: {subkey}/{name}")
                    continue
                cursor.execute('INSERT OR IGNORE INTO RecentDocs (subkey, name, data, type) VALUES (?, ?, ?, ?)',
                              (subkey, name, parsed_filename, value_type))
        print("RecentDocs key and subkeys data inserted into database successfully.")
        typed_paths_key_path = "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\TypedPaths"
        # Create table for TypedPaths key
        cursor.execute('CREATE TABLE IF NOT EXISTS TypedPaths (name TEXT, data TEXT, type TEXT)')
        typed_paths_key = reg_Claw_live(HKEY_CURRENT_USER, typed_paths_key_path)
        for name, (data, value_type) in typed_paths_key.items():
            if check_exists(cursor, 'TypedPaths', ['name', 'data', 'type'], (name, str(data), value_type)):
                logging.info(f"Skipping duplicate TypedPaths entry: {name}")
                continue
            cursor.execute('INSERT OR IGNORE INTO TypedPaths (name, data, type) VALUES (?, ?, ?)',
                          (name, str(data), value_type))
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
                            last_write_dt = datetime.datetime(1970, 1, 1) + datetime.timedelta(microseconds=microseconds)
                            most_recent_access = last_write_dt.strftime('%Y-%m-%d %H:%M:%S')
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
                                access_date = most_recent_access
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
                   
                    if check_exists(cursor, 'OpenSaveMRU', ['subkey', 'name', 'data', 'type'], (subkey, name, str(data), value_type)):
                        logging.info(f"Skipping duplicate OpenSaveMRU entry: {subkey}/{name}")
                        continue
                    cursor.execute('INSERT OR IGNORE INTO OpenSaveMRU (subkey, name, type, file_path, file_name, extension, drive_letter, access_date, data, analyzing_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                                  (subkey, name, value_type, file_path, file_name, extension, drive_letter, access_date, str(data), datetime.datetime.now().isoformat()))
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
                        last_write_dt = datetime.datetime(1970, 1, 1) + datetime.timedelta(microseconds=microseconds)
                        most_recent_access = last_write_dt.strftime('%Y-%m-%d %H:%M:%S')
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
               
                if check_exists(cursor, 'LastSaveMRU', ['mru_number', 'data', 'type'], (name, str(data), value_type)):
                    logging.info(f"Skipping duplicate LastSaveMRU entry: {name}")
                    continue
                cursor.execute('INSERT OR IGNORE INTO LastSaveMRU (mru_number, type, application, folder_path, folder_name, drive_letter, access_date, data, analyzing_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                              (name, value_type, application, folder_path, folder_name, drive_letter, access_date, str(data), datetime.datetime.now().isoformat()))
            print("LastSaveMRU has been inserted into database successfully with enhanced information.")
        except Exception as e:
            logging.error(f"Error accessing LastVisitedPidlMRU: {e}")
        # Read and insert data from DAM subkeys with enhanced information
        try:
            dam_path = "SYSTEM\\CurrentControlSet\\Services\\dam\\UserSettings"
            dam_subkeys = get_subkeys_live(HKEY_LOCAL_MACHINE, dam_path)
            for subkey, values in dam_subkeys.items():
                for name, (data, value_type) in values.items():
                    # Initialize default values
                    app_name = ""
                    process_path = ""
                    last_execution = ""
                    # Use binary parser for REG_BINARY data
                    if value_type == "REG_BINARY" and isinstance(data, bytes):
                        try:
                            parsed_data = registry_binary_parser.parse_dam_entry(name, data)
                            app_name = parsed_data.get('app_name', '')
                            process_path = parsed_data.get('process_path', '')
                            last_execution = parsed_data.get('last_execution', '')
                        except Exception as e:
                            logging.error(f"Error parsing DAM binary data for {subkey}/{name}: {e}")
                            # Fallback to original decoding attempt
                            try:
                                app_path = data.decode('utf-16-le', errors='ignore').strip('\x00')
                                if app_path and len(app_path) > 1:
                                    app_name = app_path.split('\\')[-1]
                                    process_path = app_path
                            except Exception as e2:
                                logging.error(f"Error in fallback decoding for {subkey}/{name}: {e2}")
                    else:
                        # For non-binary data, try to extract from value name
                        process_path = name
                        if '\\' in process_path:
                            app_name = process_path.split('\\')[-1]
                        else:
                            app_name = process_path
                   
                    # Try to extract timestamp from the name if not already parsed
                    if not last_execution:
                        try:
                            if '\\' in name:
                                # Some DAM entries have timestamps in the name
                                time_part = name.split('\\')[-1]
                                if time_part.isdigit() and len(time_part) > 8:
                                    filetime = int(time_part)
                                    dt = datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=filetime/10)
                                    last_execution = dt.isoformat()
                        except Exception as e:
                            logging.error(f"Error processing DAM timestamp for {subkey}/{name}: {e}")
                    if check_exists(cursor, 'DAM', ['subkey', 'name', 'data', 'type'], (subkey, name, str(data), value_type)):
                        logging.info(f"Skipping duplicate DAM entry: {subkey}/{name}")
                        continue
                    cursor.execute('INSERT OR IGNORE INTO DAM (subkey, name, data, type, app_name, last_execution) VALUES (?, ?, ?, ?, ?, ?)',
                                  (subkey, name, str(data), value_type, app_name, last_execution))
            print("DAM key and subkeys data inserted into database successfully with enhanced information.")
        except Exception as e:
            logging.error(f"Error accessing DAM: {e}")
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
                                    first_connected = datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=filetime/10)
                                    first_connected = first_connected.isoformat()
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
                                    last_connected = datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=filetime/10)
                                    last_connected = last_connected.isoformat()
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
                                    last_removed = datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=filetime/10)
                                    last_removed = last_removed.isoformat()
                                except:
                                    last_removed = str(data)
                    except Exception as e:
                        logging.error(f"Error accessing USBSTOR last removal time for {device_class}\\{serial_number}: {e}")
               
                    # Insert into USB storage devices table
                    cursor.execute('''
                    INSERT OR IGNORE INTO USBStorageDevices
                    (device_id, friendly_name, serial_number, vendor_id, product_id, revision, first_connected, last_connected, last_removed, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (f"{device_class}\\{serial_number}", friendly_name, serial_number, vendor_id, product_id, revision,
                     first_connected, last_connected, last_removed, datetime.datetime.now().isoformat()))
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
                                            (device_id, volume_guid, volume_name, drive_letter, timestamp)
                                            VALUES (?, ?, ?, ?, ?)''',
                                            (candidate_id, volume_guid, "", drive_letter, datetime.datetime.now().isoformat()))
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
            for name, (url, _) in typed_urls.items():
                # TypedURLs are stored as url1, url2, etc.
                if check_exists(cursor, 'BrowserHistory', ['browser', 'url'], ("Internet Explorer/Edge", str(url))):
                    logging.info(f"Skipping duplicate BrowserHistory entry: {url}")
                    continue
                cursor.execute('''
                INSERT INTO BrowserHistory
                (browser, url, title, visit_count, last_visit, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)''',
                ("Internet Explorer/Edge", str(url), "", 0, "", datetime.datetime.now().isoformat()))
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
                    (display_name, display_version, publisher, install_date, install_location, uninstall_string, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?)''',
                    (display_name, display_version, publisher, install_date, install_location, uninstall_string,
                     datetime.datetime.now().isoformat()))
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
                        (display_name, display_version, publisher, install_date, install_location, uninstall_string, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?, ?)''',
                        (display_name, display_version, publisher, install_date, install_location, uninstall_string,
                         datetime.datetime.now().isoformat()))
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
                (service_name, display_name, description, image_path, start_type, service_type, error_control, status, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (service_name, display_name, description, image_path, start_type, service_type, error_control, status,
                 datetime.datetime.now().isoformat()))
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
                                    last_connected = datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=filetime/10)
                                    last_connected = last_connected.isoformat()
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
                    (user_sid, username, profile_path, profile_image_path, profile_loaded, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)''',
                    (sid, username, profile_path, profile_image_path, profile_loaded, 
                     datetime.datetime.now().isoformat()))
                    
                    user_count += 1
                    
                except Exception as e:
                    logging.error(f"Error processing user profile {sid}: {e}")
                    continue
            
            # Report collection results
            print(f"User profile information collected successfully. Total users: {user_count}")
            print(f"  ✓ Collected: User SIDs, usernames, profile paths, and load status")
            
        except Exception as e:
            logging.error(f"Error collecting user profile information: {e}")
            print(f"Warning: Could not collect complete user profile information: {e}")
        
        # Collect MUICache data (Application execution history with friendly names)
        try:
            print("Collecting MUICache data...")
            
            # MUICache registry path
            muicache_path = "Software\\Classes\\Local Settings\\Software\\Microsoft\\Windows\\Shell\\MuiCache"
            
            # Create MUICache table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS MUICache (
                app_path TEXT,
                app_name TEXT,
                file_extension TEXT,
                analyzing_date TEXT
            )''')
            
            # Get MUICache values
            muicache_values = reg_Claw_live(HKEY_CURRENT_USER, muicache_path)
            
            muicache_count = 0
            for name, (data, value_type) in muicache_values.items():
                try:
                    # MUICache registry value names have format: path\filename.ext.PropertyName
                    # Examples: 
                    #   Sb\Discord.exe.ApplicationCompany
                    #   Sb\Discord.exe.FriendlyAppName
                    # We need to remove the property suffix to get the actual file path
                    
                    # Remove MUICache property suffixes
                    property_suffixes = [
                        '.ApplicationCompany',
                        '.FriendlyAppName', 
                        '.CompanyName',
                        '.FileDescription',
                        '.ProductName',
                        '.ProductVersion',
                        '.FileVersion'
                    ]
                    
                    app_path = name
                    for suffix in property_suffixes:
                        if app_path.endswith(suffix):
                            app_path = app_path[:-len(suffix)]
                            break
                    
                    # Extract application name from path
                    app_name = ""
                    if '\\' in app_path:
                        app_name = app_path.split('\\')[-1]
                    else:
                        app_name = app_path
                    
                    # Extract REAL file extension from the actual filename
                    file_extension = ""
                    if '.' in app_name:
                        # Get the actual file extension (exe, dll, bat, msc, etc.)
                        file_extension = app_name.split('.')[-1].lower()
                    
                    # Check for duplicates (use cleaned app_path)
                    if check_exists(cursor, 'MUICache', ['app_path'], (app_path,)):
                        logging.debug(f"Skipping duplicate MUICache entry: {app_path}")
                        continue
                    
                    # Insert into database
                    cursor.execute('''
                    INSERT OR IGNORE INTO MUICache 
                    (app_path, app_name, file_extension, analyzing_date)
                    VALUES (?, ?, ?, ?)''',
                    (app_path, app_name, file_extension, datetime.datetime.now().isoformat()))
                    
                    muicache_count += 1
                    
                except Exception as e:
                    logging.error(f"Error processing MUICache entry {name}: {e}")
                    continue
            
            print(f"MUICache data collected successfully. Total entries: {muicache_count}")
            print(f"  ✓ Collected: Application paths, names, and file extensions")
            
        except Exception as e:
            logging.error(f"Error collecting MUICache data: {e}")
            print(f"Warning: Could not collect complete MUICache data: {e}")
        
        # Commit the transaction
        conn.commit()
        print(f"Registry data collection complete. Data saved to {db_filename}")
    return db_filename
if __name__ == "__main__":
    main_live_reg()
