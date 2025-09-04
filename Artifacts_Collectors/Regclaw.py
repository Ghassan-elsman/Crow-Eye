import sqlite3
import winreg
import os
import datetime
import logging
import ctypes
import platform

# Configure logging
logging.basicConfig(filename='regclaw_errors.log', level=logging.ERROR, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

def check_admin_privileges():
    """Check if the script is running with administrative privileges."""
    if platform.system() != "Windows":
        print("Error: This script is designed for Windows systems only.")
        exit(1)
    if not ctypes.windll.shell32.IsUserAnAdmin():
        print("Error: This script requires administrative privileges.")
        exit(1)

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
    # Check administrative privileges
    check_admin_privileges()
    
    # Set the database filename based on the provided db_path or use default
    if db_path:
        db_filename = db_path
    else:
        db_filename = "registry_data_live.db"
    
    # Use case_root if provided
    if case_root:
        os.makedirs(case_root, exist_ok=True)
        db_filename = os.path.join(case_root, db_filename)
    
    # Call the main registry collection function with the database path
    return main_live_reg(db_filename)

def main_live_reg(db_filename='registry_data_live.db'):
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

                        # Handle binary data
                        if value_type == winreg.REG_BINARY:
                            if isinstance(data, bytes):
                                try:
                                    # Try to convert binary data to string if possible
                                    data = data.decode('utf-16-le')
                                except (UnicodeDecodeError, AttributeError):
                                    try:
                                        data = data.decode('ascii', errors='ignore')
                                    except:
                                        data = str(data)

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

                                    # Handle binary data
                                    if value_type == winreg.REG_BINARY:
                                        if isinstance(data, bytes):
                                            try:
                                                # Try to convert binary data to string if possible
                                                data = data.decode('utf-16-le')
                                            except (UnicodeDecodeError, AttributeError):
                                                try:
                                                    data = data.decode('ascii', errors='ignore')
                                                except:
                                                    data = str(data)

                                    subkey_values[subkey_name][name] = (data, value_type_str)
                                    j += 1
                                except WindowsError:
                                    break
                    except Exception as e:
                        logging.error(f"Error reading subkey {subkey_path}: {e}")

            return subkey_values
        except Exception as e:
            logging.error(f"Error reading subkeys for {key_path}: {e}")
            return {}

    # Define registry hive constants
    HKEY_CURRENT_USER = winreg.HKEY_CURRENT_USER
    HKEY_LOCAL_MACHINE = winreg.HKEY_LOCAL_MACHINE

    # Define paths for Run, RunOnce, DAM, BAM and Search keys
    paths = {
        "machine_run": (HKEY_LOCAL_MACHINE, "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run"),
        "machine_run_once": (HKEY_LOCAL_MACHINE, "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\RunOnce"),
        "user_run": (HKEY_CURRENT_USER, "Software\\Microsoft\\Windows\\CurrentVersion\\Run"),
        "user_run_once": (HKEY_CURRENT_USER, "Software\\Microsoft\\Windows\\CurrentVersion\\RunOnce"),
        "dam": (HKEY_LOCAL_MACHINE, "SYSTEM\\CurrentControlSet\\Services\\dam\\UserSettings"),
        "bam": (HKEY_LOCAL_MACHINE, "SYSTEM\\CurrentControlSet\\Services\\bam\\State\\UserSettings"),
        "search_history": (HKEY_CURRENT_USER, "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\WordWheelQuery")
    }

    # Define table name mapping
    table_name_mapping = {
        "machine_run": "machine_run",
        "machine_run_once": "machine_run_once",
        "user_run": "user_run",
        "user_run_once": "user_run_once",
        "dam": "DAM",
        "bam": "BAM",
        "search_history": "SearchHistory"
    }

    # Create a timestamp for the database filename
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    db_filename = 'registry_data_live.db'

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
            ("shutdown_information", "name TEXT, data TEXT, type TEXT"),
            ("Search_Explorer_bar", "name TEXT, data TEXT, type TEXT")
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
            timestamp TEXT
        )''')

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

        # Enhanced Search History table with categorization
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS SearchHistory (
            search_term TEXT,
            search_type TEXT,
            frequency INTEGER,
            last_used TEXT,
            mru_list_position INTEGER,
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
            data TEXT, 
            type TEXT,
            file_path TEXT,
            extension TEXT,
            access_date TEXT
        )''')

        # Enhanced LastSaveMRU table with readable information
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS lastSaveMRU (
            name TEXT, 
            data TEXT, 
            type TEXT,
            folder_path TEXT,
            application TEXT,
            access_date TEXT
        )''')

        # Insert data into the respective tables
        for table_name, (hive, key) in paths.items():
            output = reg_Claw_live(hive, key)
            db_table_name = table_name_mapping.get(table_name, table_name)
            for name, (data, value_type) in output.items():
                try:
                    # Check if entry exists for tables without primary keys
                    if db_table_name in ['machine_run', 'machine_run_once', 'user_run', 'user_run_once', 'DAM', 'BAM', 'SearchHistory']:
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
                    # Extract process information
                    process_path = str(data)
                    app_name = os.path.basename(process_path) if process_path else ''
                    sid = subkey.split('\\')[-1] if '\\' in subkey else subkey
                    
                    # Convert binary timestamp if present
                    last_execution = ''
                    execution_count = 0
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
                    # Extract process information
                    process_path = str(data)
                    app_name = os.path.basename(process_path) if process_path else ''
                    sid = subkey.split('\\')[-1] if '\\' in subkey else subkey
                    
                    # Extract execution flags and timestamp
                    last_execution = ''
                    execution_flags = 0
                    if 'Flags' in values:
                        try:
                            execution_flags = int(values['Flags'][0])
                        except:
                            pass
                    if 'LastExecutionTime' in values:
                        try:
                            filetime = int(values['LastExecutionTime'][0])
                            dt = datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=filetime/10)
                            last_execution = dt.isoformat()
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

        # Explorer Search History collection
        search_data = reg_Claw_live(HKEY_CURRENT_USER, paths['search_history'][1])
        
        # Process search history
        for name, (data, value_type) in search_data.items():
            try:
                if name == 'MRUListEx':
                    continue  # Skip the MRU order list
                
                search_term = str(data)
                search_type = 'File' if '\\' in search_term else 'General'
                frequency = 1  # Default frequency
                mru_position = -1
                
                # Try to get the MRU position
                if 'MRUListEx' in search_data:
                    try:
                        mru_list = search_data['MRUListEx'][0]
                        if isinstance(mru_list, bytes):
                            # Convert bytes to list of integers (DWORD values)
                            mru_values = [mru_list[i:i+4] for i in range(0, len(mru_list), 4)]
                            mru_position = mru_values.index(int(name).to_bytes(4, 'little')) if int(name) < len(mru_values) else -1
                    except:
                        pass

                # Check if entry exists
                if check_exists(cursor, 'SearchHistory', ['search_term', 'search_type'], (search_term, search_type)):
                    logging.info(f"Skipping duplicate SearchHistory entry: {search_term}")
                    continue

                cursor.execute('INSERT OR IGNORE INTO SearchHistory (search_term, search_type, frequency, last_used, mru_list_position, timestamp) VALUES (?, ?, ?, ?, ?, ?)',
                              (search_term, search_type, frequency, datetime.datetime.now().isoformat(), mru_position, datetime.datetime.now().isoformat()))
            except Exception as e:
                logging.error(f"Error processing search history entry {name}: {e}")

        print("Explorer search history data inserted into database successfully.")

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

        # Files and folders activities - searches via the Explorer search bar
        searches_explorer_path = "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\WordWheelQuery"
        try:
            searches_explorer_regkey = reg_Claw_live(HKEY_CURRENT_USER, searches_explorer_path)

            # Insert data into the 'Search_Explorer_bar' table
            for name, (data, value_type) in searches_explorer_regkey.items():
                if check_exists(cursor, 'Search_Explorer_bar', ['name', 'data', 'type'], (name, str(data), value_type)):
                    logging.info(f"Skipping duplicate Search_Explorer_bar entry: {name}")
                    continue
                cursor.execute('INSERT OR IGNORE INTO Search_Explorer_bar (name, data, type) VALUES (?, ?, ?)', 
                              (name, str(data), value_type))

            print("Searches via explorer search bar have been inserted successfully.")
        except Exception as e:
            logging.error(f"Error accessing WordWheelQuery: {e}")

        # Recent opened docs
        recent_docs_path = "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\RecentDocs"

        # Create a single table for RecentDocs key and subkeys
        cursor.execute('CREATE TABLE IF NOT EXISTS RecentDocs (subkey TEXT, name TEXT, data TEXT, type TEXT)')

        # Read and insert data from RecentDocs key
        recent_docs_key = reg_Claw_live(HKEY_CURRENT_USER, recent_docs_path)
        for name, (data, value_type) in recent_docs_key.items():
            if check_exists(cursor, 'RecentDocs', ['subkey', 'name', 'data', 'type'], ('main key', name, str(data), value_type)):
                logging.info(f"Skipping duplicate RecentDocs entry: main key/{name}")
                continue
            cursor.execute('INSERT OR IGNORE INTO RecentDocs (subkey, name, data, type) VALUES (?, ?, ?, ?)', 
                          ('main key', name, str(data), value_type))

        # Read and insert data from RecentDocs subkeys
        recent_docs_subkeys = get_subkeys_live(HKEY_CURRENT_USER, recent_docs_path)
        for subkey, values in recent_docs_subkeys.items():
            for name, (data, value_type) in values.items():
                if check_exists(cursor, 'RecentDocs', ['subkey', 'name', 'data', 'type'], (subkey, name, str(data), value_type)):
                    logging.info(f"Skipping duplicate RecentDocs entry: {subkey}/{name}")
                    continue
                cursor.execute('INSERT OR IGNORE INTO RecentDocs (subkey, name, data, type) VALUES (?, ?, ?, ?)', 
                              (subkey, name, str(data), value_type))

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
                for name, (data, value_type) in values.items():
                    file_path = ""
                    extension = subkey  # The subkey is often the file extension
                    access_date = ""

                    # Try to extract file path from MRU data
                    if value_type == "REG_BINARY" and isinstance(data, bytes):
                        try:
                            # Look for string data in the binary blob
                            possible_path = data.decode('utf-16-le', errors='ignore').strip('\x00')
                            # Clean up the path - remove non-printable characters
                            clean_path = ''.join(c for c in possible_path if c.isprintable() or c in [' ', '\\', '/', '.', ':', '-'])

                            # If it looks like a path, use it
                            if '\\' in clean_path and len(clean_path) > 5:
                                file_path = clean_path
                        except:
                            pass
                    
                    # Try to get access date from MRUListEx
                    if name.lower() == 'mrulistex' and isinstance(data, bytes):
                        try:
                            # MRUListEx often contains the order of recently used items
                            # The first 4 bytes typically represent the most recently used item
                            if len(data) >= 4:
                                # We don't have the actual date, but we can note it was the most recent
                                access_date = "Most recent"
                        except:
                            pass
                    
                    if check_exists(cursor, 'OpenSaveMRU', ['subkey', 'name', 'data', 'type'], (subkey, name, str(data), value_type)):
                        logging.info(f"Skipping duplicate OpenSaveMRU entry: {subkey}/{name}")
                        continue
                    cursor.execute('INSERT OR IGNORE INTO OpenSaveMRU (subkey, name, data, type, file_path, extension, access_date) VALUES (?, ?, ?, ?, ?, ?, ?)', 
                                  (subkey, name, str(data), value_type, file_path, extension, access_date))

            print("OpenSaveMRU subkeys data inserted into database successfully with enhanced information.")
        except Exception as e:
            logging.error(f"Error accessing OpenSavePidlMRU: {e}")

        # Track directories that were accessed by applications - Enhanced version
        last_savemru_path = "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\ComDlg32\\LastVisitedPidlMRU"
        try:
            lastsavemru_regkey = reg_Claw_live(HKEY_CURRENT_USER, last_savemru_path)

            for name, (data, value_type) in lastsavemru_regkey.items():
                folder_path = ""
                application = ""
                access_date = ""

                # Try to extract folder path and application from MRU data
                if value_type == "REG_BINARY" and isinstance(data, bytes):
                    try:
                        # The binary data often contains both the application name and folder path
                        text_data = data.decode('utf-16-le', errors='ignore').strip('\x00')
                        parts = text_data.split('\x00')

                        # Filter out empty parts and non-printable characters
                        clean_parts = [''.join(c for c in part if c.isprintable() or c in [' ', '\\', '/', '.', ':', '-']) 
                                      for part in parts if part.strip()]

                        if clean_parts:
                            # First part is often the application name
                            if len(clean_parts) > 0 and len(clean_parts[0]) > 1:
                                application = clean_parts[0]

                            # Look for a part that looks like a folder path
                            for part in clean_parts:
                                if '\\' in part and len(part) > 5:
                                    folder_path = part
                                    break
                    except:
                        pass
                
                # Try to determine if this is the most recent entry
                if name.lower() == 'mrulistex' and isinstance(data, bytes):
                    try:
                        if len(data) >= 4:
                            access_date = "Most recent"
                    except:
                        pass
                
                if check_exists(cursor, 'lastSaveMRU', ['name', 'data', 'type'], (name, str(data), value_type)):
                    logging.info(f"Skipping duplicate lastSaveMRU entry: {name}")
                    continue
                cursor.execute('INSERT OR IGNORE INTO lastSaveMRU (name, data, type, folder_path, application, access_date) VALUES (?, ?, ?, ?, ?, ?)', 
                              (name, str(data), value_type, folder_path, application, access_date))

            print("LastSaveMRU has been inserted into database successfully with enhanced information.")
        except Exception as e:
            logging.error(f"Error accessing LastVisitedPidlMRU: {e}")

        # Read and insert data from DAM subkeys with enhanced information
        try:
            dam_path = "SYSTEM\\CurrentControlSet\\Services\\dam\\UserSettings"
            dam_subkeys = get_subkeys_live(HKEY_LOCAL_MACHINE, dam_path)
            for subkey, values in dam_subkeys.items():
                for name, (data, value_type) in values.items():
                    app_name = ""
                    last_execution = ""

                    # Try to extract application name from the binary data
                    if value_type == "REG_BINARY" and isinstance(data, bytes):
                        try:
                            # Application path is often stored in the binary data as a UTF-16 string
                            app_path = data.decode('utf-16-le', errors='ignore').strip('\x00')
                            if app_path and len(app_path) > 1:
                                app_name = app_path.split('\\')[-1]  # Extract filename from path
                        except Exception as e:
                            logging.error(f"Error decoding DAM binary data for {subkey}/{name}: {e}")
                    
                    # Try to extract timestamp from the name (often contains FILETIME)
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

                    # Get instance properties
                    for name, (data, _) in instance_values.items():
                        if name.lower() == "friendlyname":
                            friendly_name = str(data)
                        elif name.lower() == "devicedesc":
                            if not friendly_name:  # Use DeviceDesc if FriendlyName not available
                                friendly_name = str(data)

                    # Try to get connection times from the device properties
                    try:
                        device_props_path = f"SYSTEM\\CurrentControlSet\\Enum\\USBSTOR\\{device_class}\\{serial_number}\\Properties\\{{83da6326-97a6-4088-9453-a1923f573b29}}\\{{2}}"
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
                        device_props_path = f"SYSTEM\\CurrentControlSet\\Enum\\USBSTOR\\{device_class}\\{serial_number}\\Properties\\{{83da6326-97a6-4088-9453-a1923f573b29}}\\{{8}}"
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
                
                    # Insert into USB storage devices table
                    cursor.execute('''
                    INSERT OR IGNORE INTO USBStorageDevices 
                    (device_id, friendly_name, serial_number, vendor_id, product_id, revision, first_connected, last_connected, timestamp) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
                    (f"{device_class}\\{serial_number}", friendly_name, serial_number, vendor_id, product_id, revision, 
                     first_connected, last_connected, datetime.datetime.now().isoformat()))

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
                            drive_letter = name[12:]  # Extract drive letter
                        elif name.startswith('\\??\\Volume'):
                            volume_guid = name[11:]  # Extract volume GUID

                        # Try to match this to a USB device
                        if isinstance(data, bytes):
                            data_str = str(data)
                            # Check if the USBStorageDevices table exists before querying it
                            try:
                                for device_id in cursor.execute('SELECT device_id FROM USBStorageDevices').fetchall():
                                    device_id = device_id[0]
                                    # If the device ID is found in the mounted device data
                                    if device_id.split('\\')[0] in data_str:
                                        if check_exists(cursor, 'USBStorageVolumes', ['device_id', 'volume_guid'], (device_id, volume_guid)):
                                            logging.info(f"Skipping duplicate USBStorageVolumes entry: {device_id}/{volume_guid}")
                                            continue
                                        cursor.execute('''
                                        INSERT OR IGNORE INTO USBStorageVolumes 
                                        (device_id, volume_guid, volume_name, drive_letter, timestamp) 
                                        VALUES (?, ?, ?, ?, ?)''', 
                                        (device_id, volume_guid, "", drive_letter, datetime.datetime.now().isoformat()))
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
                            unlink_string = str(data)

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
                        device_props_path = f"SYSTEM\\CurrentControlSet\\Enum\\USB\\{device_id}\\{instance_id}\\Properties\\{{83da6326-97a6-4088-9453-a1923f573b29}}\\{{8}}"
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
                                for _, (data, value_type) in property_values.items():
                                    property_name = f"{category_id}\\{property_id}"
                                    cursor.execute('''
                                    INSERT OR IGNORE INTO USBProperties 
                                    (device_id, property_name, property_value, property_type) 
                                    VALUES (?, ?, ?, ?)''', 
                                    (f"{device_id}\\{instance_id}", property_name, str(data), value_type))
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

        # Commit the transaction
        conn.commit()
        print(f"Registry data collection complete. Data saved to {db_filename}")

    return db_filename

if __name__ == "__main__":
    main_live_reg()
