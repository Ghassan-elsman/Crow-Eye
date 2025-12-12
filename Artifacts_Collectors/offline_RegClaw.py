def reg_Claw(case_root=None, offline_mode=False, windows_partition="C:"):    
    import sqlite3
    from Registry import Registry
    print("Import successful")
    import binascii
    import os

    # Define paths to the registry hives based on case management
    if offline_mode and case_root:
        # Use registry hives from the case directory
        registry_dir = os.path.join(case_root, "Target_Artifacts", "Registry_Hives")
        Ntuser_reg_hive = os.path.join(registry_dir, "NTUSER.DAT")
        system_reg_hive = os.path.join(registry_dir, "SYSTEM")
        Software_reg_hive = os.path.join(registry_dir, "SOFTWARE")
        
        # Create database in the case artifacts directory
        db_path = os.path.join(case_root, "Target_Artifacts", "registry_data.db")
        
        print(f"[Offline Registry] Using registry hives from: {registry_dir}")
        print(f"[Offline Registry] NTUSER.DAT: {Ntuser_reg_hive}")
        print(f"[Offline Registry] SYSTEM: {system_reg_hive}")
        print(f"[Offline Registry] SOFTWARE: {Software_reg_hive}")
    else:
        # Use default paths for live system analysis
        # Note: os.getenv('SystemRoot') already provides dynamic partition detection
        # The windows_partition parameter is available for explicit override if needed
        system_root = os.getenv('SystemRoot', f'{windows_partition}\\Windows')
        user_profile = os.getenv('USERPROFILE', f'{windows_partition}\\Users\\Default')
        
        Ntuser_reg_hive = os.path.join(user_profile, 'NTUSER.DAT')
        system_reg_hive = os.path.join(system_root, 'System32', 'config', 'SYSTEM')
        Software_reg_hive = os.path.join(system_root, 'System32', 'config', 'SOFTWARE')
        
        print(f"[Registry] Using Windows partition: {windows_partition}")
        print(f"[Registry] SystemRoot: {system_root}")

        # Fallback to local paths if needed
        if not os.path.exists(Ntuser_reg_hive) or not os.path.exists(system_reg_hive) or not os.path.exists(Software_reg_hive):
            Ntuser_reg_hive = r"Artifacts_Collectors\Target Artifacts\Registry Hives\NTUSER.DAT"
            system_reg_hive = r"Artifacts_Collectors\Target Artifacts\Registry Hives\SYSTEM"
            Software_reg_hive = r"Artifacts_Collectors\Target Artifacts\Registry Hives\SOFTWARE"
        
        # Use default database path
        db_path = 'registry_data.db'

    # Check if the paths are valid
    if not os.path.exists(Ntuser_reg_hive) or not os.path.exists(system_reg_hive) or not os.path.exists(Software_reg_hive):
        print(f"[Registry Error] One or more registry hive paths are invalid:")
        print(f"[Registry Error] NTUSER.DAT: {Ntuser_reg_hive} - Exists: {os.path.exists(Ntuser_reg_hive)}")
        print(f"[Registry Error] SYSTEM: {system_reg_hive} - Exists: {os.path.exists(system_reg_hive)}")
        print(f"[Registry Error] SOFTWARE: {Software_reg_hive} - Exists: {os.path.exists(Software_reg_hive)}")
        raise ValueError("One or more registry hive paths are invalid. Please check the paths.")

    # Function to read registry values and their types
    def read_registry_values(hive, key):
        try:
            reg = Registry.Registry(hive)
            key = reg.open(key)
            values = {}
            for value in key.values():
                name = value.name()
                data = value.value()
                value_type = value.value_type()
                if value_type == Registry.RegBin:
                    # Convert binary data to ASCII if possible
                    try:
                        data = data.decode('utf-16-le')
                    except UnicodeDecodeError:
                        pass  # Leave data unchanged if it cannot be decoded to ASCII
                    value_type_str = "REG_BINARY"
                else:
                    value_type_str = {
                        Registry.RegSZ: "REG_SZ",
                        Registry.RegExpandSZ: "REG_EXPAND_SZ",
                        Registry.RegDWord: "REG_DWORD",
                        Registry.RegQWord: "REG_QWORD"
                    }.get(value_type, "UNKNOWN")
                values[name] = (data, value_type_str)
            return values
        except Exception as e:
            print(f"Error reading registry key {key}: {e}")
            return {}

    # Function to handle subkeys and their values
    def get_subkeys(hive, key):
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
                    if value_type == Registry.RegBin:
                        # Convert binary data to ASCII if possible
                        try:
                            data = data.decode('utf-16-le')
                        except UnicodeDecodeError:
                            pass  # Leave data unchanged if it cannot be decoded to ASCII
                        value_type_str = "REG_BINARY"
                    else:
                        value_type_str = {
                            Registry.RegSZ: "REG_SZ",
                            Registry.RegExpandSZ: "REG_EXPAND_SZ",
                            Registry.RegDWord: "REG_DWORD",
                            Registry.RegQWord: "REG_QWORD"
                        }.get(value_type, "UNKNOWN")
                    subkey_values[subkey.name()][name] = (data, value_type_str)
            return subkey_values
        except Exception as e:
            print(f"Error reading subkeys for {key}: {e}")
            return {}


    # Define paths for Run and RunOnce registry keys
    paths = {
        "machine_run": (Software_reg_hive, "Microsoft\\Windows\\CurrentVersion\\Run"),
        "machine_run_once": (Software_reg_hive, "Microsoft\\Windows\\CurrentVersion\\RunOnce"),
        "user_run": (Ntuser_reg_hive, "Software\\Microsoft\\Windows\\CurrentVersion\\Run"),
        "user_run_once": (Ntuser_reg_hive, "Software\\Microsoft\\Windows\\CurrentVersion\\RunOnce")
    }

    # Connect to SQLite database (or create it if it doesn't exist)
    conn = sqlite3.connect(db_path)
    print(f"[Registry] Using database: {db_path}")
    cursor = conn.cursor()
    
    # Create tables if they don't exist
    tables = [
        ("machine_run", "name TEXT, data TEXT, type INTEGER"),
        ("machine_run_once", "name TEXT, data TEXT, type INTEGER"),
        ("user_run", "name TEXT, data TEXT, type INTEGER"),
        ("user_run_once", "name TEXT, data TEXT, type INTEGER"),
        ("Network_list", "subkey TEXT, name TEXT, data TEXT, type INTEGER"),
        ("Windows_lastupdate", "name TEXT, data TEXT, type INTEGER"),
        ("Windows_lastupdate_subkeys", "subkey TEXT, name TEXT, data TEXT, type INTEGER"),
        ("computer_Name", "name TEXT, data TEXT, type INTEGER"),
        ("time_zone", "name TEXT, data TEXT, type INTEGER"),
        ("network_interfaces", "subkey TEXT, name TEXT, data TEXT, type INTEGER"),
        ("shutdown_information", "name TEXT, data TEXT, type INTEGER"),
        ("Search_Explorer_bar", "name TEXT, data TEXT, type INTEGER")
    ]

    for table_name, schema in tables:
        cursor.execute(f'CREATE TABLE IF NOT EXISTS {table_name} ({schema})')

    # Insert data into the respective tables
    for table_name, (hive, key) in paths.items():
        output = read_registry_values(hive, key)
        for name, (data, value_type) in output.items():
            cursor.execute(f'INSERT INTO {table_name} (name, data, type) VALUES (?, ?, ?)', (name, data, value_type))

    print("Auto start programs data inserted into database successfully.")

    # Network List Keys
    Netlist_reg_key = "Microsoft\\Windows NT\\CurrentVersion\\NetworkList\\Signatures\\Unmanaged"
    Networklosts_subkeys = get_subkeys(Software_reg_hive, Netlist_reg_key)

    # Insert data into the 'Network_list' table
    for subkey, values in Networklosts_subkeys.items():
        first_network_value = values.get('FirstNetwork', ('N/A', None))[0]
        for name, (data, value_type) in values.items():
            cursor.execute('INSERT INTO Network_list (subkey, name, data, type) VALUES (?, ?, ?, ?)', (str(first_network_value), name, str(data), value_type))

    print("Network list key data inserted into database successfully.")


    # Windows Last update
    last_update_path = "Microsoft\\Windows\\CurrentVersion\\WindowsUpdate"
    last_update_regkey = read_registry_values(Software_reg_hive, last_update_path)
    last_update_subkey = get_subkeys(Software_reg_hive, last_update_path)

    # Insert data into the 'Windows_lastupdate' table
    for name, (data, value_type) in last_update_regkey.items():
        cursor.execute('INSERT INTO Windows_lastupdate (name, data, type) VALUES (?, ?, ?)', (name, str(data), value_type))

    # Insert data into the 'Windows_lastupdate_subkeys' table
    for subkey, values in last_update_subkey.items():
        for name, (data, value_type) in values.items():
            cursor.execute('INSERT INTO Windows_lastupdate_subkeys (subkey, name, data, type) VALUES (?, ?, ?, ?)', (str(subkey), name, str(data), value_type))

    print("Windows last update key data inserted into database successfully.")

    # Computer Name
    computerName_reg_path = 'ControlSet001\\Control\\ComputerName\\ComputerName'
    ComputerName_reg_key = read_registry_values(system_reg_hive, computerName_reg_path)

    # Insert data into the 'computer_Name' table
    for name, (data, value_type) in ComputerName_reg_key.items():
        cursor.execute('INSERT INTO computer_Name (name, data, type) VALUES (?, ?, ?)', (name, data, value_type))

    print("Computer name data inserted into database successfully.")

    # Time zone information
    timeZone_path = 'ControlSet001\\Control\\TimeZoneInformation'
    timezone_reg_key = read_registry_values(system_reg_hive, timeZone_path)

    # Insert data into the 'time_zone' table
    for name, (data, value_type) in timezone_reg_key.items():
        cursor.execute('INSERT INTO time_zone (name, data, type) VALUES (?, ?, ?)', (name, data, value_type))

    print("Time zone information inserted into database successfully.")

    # Network interfaces information
    networkInterface_path = 'ControlSet001\\Services\\Tcpip\\Parameters\\Interfaces'
    network_interfaces_sub_key = get_subkeys(system_reg_hive, networkInterface_path)

    # Insert data into the 'network_interfaces' table
    for subkey, values in network_interfaces_sub_key.items():
        for name, (data, value_type) in values.items():
            cursor.execute('INSERT INTO network_interfaces (subkey, name, data, type) VALUES (?, ?, ?, ?)', (str(subkey), name, str(data), value_type))

    print("Network interfaces information inserted into database successfully.")

    # Shutdown information
    shutdown_path = 'ControlSet001\\Control\\Windows'
    shutdown_reg_key = read_registry_values(system_reg_hive, shutdown_path)

    # Insert data into the 'shutdown_information' table
    for name, (data, value_type) in shutdown_reg_key.items():
        cursor.execute('INSERT INTO shutdown_information (name, data, type) VALUES (?, ?, ?)', (name, data, value_type))

    print('Shutdown information inserted into database successfully.')

    # Files and folders activities - searches via the Explorer search bar
    searches_explorer_path = "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\WordWheelQuery"
    searches_explorer_regkey = read_registry_values(Ntuser_reg_hive, searches_explorer_path)


    # Insert data into the 'Search_Explorer_bar' table
    for name, (data, value_type) in searches_explorer_regkey.items():
        cursor.execute('INSERT INTO Search_Explorer_bar (name, data, type) VALUES (?, ?, ?)', (name, data, value_type))

    print("Searches via explorer search bar have been inserted successfully.")

    # Commit the transaction and close the database connection
    conn.commit()


    # Recent opened docs
    recent_docs_path = "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\RecentDocs"

    #Create a single table for RecentDocs key and subkeys
    cursor.execute('CREATE TABLE IF NOT EXISTS RecentDocs (subkey TEXT, name TEXT, data TEXT, type TEXT)')

    # Read and insert data from RecentDocs key
    recent_docs_key = read_registry_values(Ntuser_reg_hive, recent_docs_path)
    for name, (data, value_type) in recent_docs_key.items():
        cursor.execute('INSERT INTO RecentDocs (subkey, name, data, type) VALUES (?, ?, ?, ?)', ('main key ', name, data, value_type))

    # Read and insert data from RecentDocs subkeys
    recent_docs_subkeys = get_subkeys(Ntuser_reg_hive, recent_docs_path)
    for subkey, values in recent_docs_subkeys.items():
        for name, (data, value_type) in values.items():
            cursor.execute('INSERT INTO RecentDocs (subkey, name, data, type) VALUES (?, ?, ?, ?)', (subkey, name, data, value_type))

    print("RecentDocs key and subkeys data inserted into database successfully.")

    typed_paths_key_path = "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\TypedPaths"
    #Create table for TypedPaths key
    cursor.execute('CREATE TABLE IF NOT EXISTS TypedPaths (name TEXT, data TEXT, type TEXT)')
    typed_paths_key = read_registry_values(Ntuser_reg_hive, typed_paths_key_path)
    for name, (data, value_type) in typed_paths_key.items():
        cursor.execute('INSERT INTO TypedPaths (name, data, type) VALUES (?, ?, ?)', (name, data, value_type))

    print("TypedPaths data inserted into database successfully.")

    # Commit the transaction and close the database connection
    conn.commit()

    #  files that have been opened or saved by Windows shell dialog box 
    shellbags_path = "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\ComDlg32\\OpenSavePidlMRU"
    #Create table for OpenSaveMRU  subkeys
    cursor.execute('CREATE TABLE IF NOT EXISTS OpenSaveMRU (subkey TEXT, name TEXT, data TEXT, type TEXT)')
    shellbags_subkeys = get_subkeys(Ntuser_reg_hive, shellbags_path)
    for subkey, values in shellbags_subkeys.items():
        for name, (data, value_type) in values.items():
            cursor.execute('INSERT INTO OpenSaveMRU (subkey, name, data, type) VALUES (?, ?, ?, ?)', (subkey, name, data, value_type))

    print("OpenSaveMRU subkeys data inserted into database successfully.")
    conn.commit()

    last_savemru_path = "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\ComDlg32\\LastVisitedPidlMRU"
    # Track directories that was accessed by the application by the last savemru
    cursor.execute('CREATE TABLE IF NOT EXISTS lastSaveMRU (name TEXT, data TEXT, type TEXT, pid INTEGER)')
    lastsavemru_regkey = read_registry_values(Ntuser_reg_hive, last_savemru_path)
    for name, (data, value_type) in lastsavemru_regkey.items():
        cursor.execute('INSERT INTO lastSaveMRU (name, data, type) VALUES (?, ?, ?)', (name, data, value_type))
    print("LastSaveMRU has been inserted into database successfully.")
    conn.commit()

    # Define the registry paths for BAM and DAM
    bam_path = "SYSTEM\\ControlSet001\\Services\\bam"
    bam_user_settings_path = "SYSTEM\\ControlSet001\\Services\\bam\\State\\UserSettings"
    dam_path = "SYSTEM\\CurrentControlSet\\Services\\dam"
    dam_user_settings_path = "SYSTEM\\CurrentControlSet\\Services\\dam\\UserSettings"
    # Create tables for BAM and DAM if they don't exist
    cursor.execute('CREATE TABLE IF NOT EXISTS BAM (subkey TEXT, name TEXT, data TEXT, type TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS DAM (subkey TEXT, name TEXT, data TEXT, type TEXT)')

    # Read and insert data from BAM main key
    bam_key = read_registry_values(system_reg_hive, bam_path)
    for name, (data, value_type) in bam_key.items():
        cursor.execute('INSERT INTO BAM (subkey, name, data, type) VALUES (?, ?, ?, ?)', ('main key', name, data, value_type))

    # Read and insert data from BAM subkeys
    bam_subkeys = get_subkeys(system_reg_hive, bam_user_settings_path)
    for subkey, values in bam_subkeys.items():
        for name, (data, value_type) in values.items():
            cursor.execute('INSERT INTO BAM (subkey, name, data, type) VALUES (?, ?, ?, ?)', (subkey, name, data, value_type))

    print("BAM key and subkeys data inserted into database successfully.")

    # Read and insert data from DAM main key
    dam_key = read_registry_values(system_reg_hive, dam_path)
    for name, (data, value_type) in dam_key.items():
        cursor.execute('INSERT INTO DAM (subkey, name, data, type) VALUES (?, ?, ?, ?)', ('main key', name, data, value_type))

    # Read and insert data from DAM subkeys
    dam_subkeys = get_subkeys(system_reg_hive, dam_user_settings_path)
    for subkey, values in dam_subkeys.items():
        for name, (data, value_type) in values.items():
            cursor.execute('INSERT INTO DAM (subkey, name, data, type) VALUES (?, ?, ?, ?)', (subkey, name, data, value_type))

    conn.commit()
    print("DAM key and subkeys data inserted into database successfully.")

    shellbags_path = "Software\\Microsoft\\Windows\\Shell"
    #Create table for shellbags subkeys
    cursor.execute('CREATE TABLE IF NOT EXISTS shellbags (subkey TEXT, name TEXT, data TEXT, type TEXT)')
    shellbags_subkeys = get_subkeys(Ntuser_reg_hive, shellbags_path)
    for subkey, values in shellbags_subkeys.items():
        for name, (data, value_type) in values.items():
            cursor.execute('INSERT INTO shellbags (subkey, name, data, type) VALUES (?, ?, ?, ?)', (subkey, name, data, value_type))

    print("shellbags subkeys data inserted into database successfully.")

    ########################################################
    # logs 

    # Create the 'USBLogs' table if it doesn't exist
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS USBLogs (
        path TEXT,
        name TEXT,
        data TEXT
    )
    ''')

    # Define the USB path
    usb_path = "SYSTEM\\ControlSet001\\Enum\\USB"

    # Parse the USB logs
    usb_data = get_subkeys(system_reg_hive, usb_path)

    # For each subkey in USB, read its subkeys using the get_subkeys function and insert the data into the USBLogs table
    for usb_subkey_path in usb_data.keys():
        usb_subkey_data = get_subkeys(system_reg_hive, usb_subkey_path)
        for sub_subkey_path in usb_subkey_data.keys():
            sub_subkey_data = get_subkeys(system_reg_hive, sub_subkey_path)
            for path, values in sub_subkey_data.items():
                for name, data in values.items():
                    cursor.execute('INSERT INTO USBLogs (path, name, data) VALUES (?, ?, ?)', (path, name, data))

    # Commit the transaction and close the database connection
    conn.commit()

    print("USB logs data inserted into database successfully.")

    # EventLog Key
    event_log_path = "CurrentControlSet\\Services\\EventLog"
    event_log_key = read_registry_values(system_reg_hive, event_log_path)
    event_log_subkeys = get_subkeys(system_reg_hive, event_log_path)

    # Create table for EventLog key and subkeys
    cursor.execute('CREATE TABLE IF NOT EXISTS EventLog (subkey TEXT, name TEXT, data TEXT, type TEXT)')

    # Insert data from EventLog key
    for name, (data, value_type) in event_log_key.items():
        cursor.execute('INSERT INTO EventLog (subkey, name, data, type) VALUES (?, ?, ?, ?)', ('event_log', name, data, value_type))

    # Insert data from EventLog subkeys
    for subkey, values in event_log_subkeys.items():
        for name, (data, value_type) in values.items():
            cursor.execute('INSERT INTO EventLog (subkey, name, data, type) VALUES (?, ?, ?, ?)', (subkey, name, data, value_type))

    print("EventLog key and subkeys data inserted into database successfully.")
    conn.commit()

    conn.close()
    print(f"\033[92m\nParsing Registry has been completed by Crow Eye\033[0m")
    print(f"Registry data saved to: {db_path}")

if __name__ == "__main__":
    reg_Claw()