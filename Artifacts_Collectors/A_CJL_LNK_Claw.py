from JLParser import Claw
import sqlite3
import os
import win32api
from datetime import datetime
import shutil

# Configure target directory structure
TARGET_BASE_DIR = os.path.join("Artifacts_Collectors", "Target Artifacts", "C,AJL and LNK")
TARGET_DIRS = {
    'recent': os.path.join(TARGET_BASE_DIR, "Recent"),  # For LNK files
    'automatic': os.path.join(TARGET_BASE_DIR, "Recent", "AutomaticDestinations"),  # For automatic jump lists
    'custom': os.path.join(TARGET_BASE_DIR, "Recent", "CustomDestinations")  # For custom jump lists
}

# System configuration
SYSTEM_DRIVE = os.environ["SystemDrive"]
USER_PROFILES_PATH = os.path.join(SYSTEM_DRIVE, "Users")

def create_target_directories():
    """Create all target directories with error handling"""
    try:
        # Create main directories
        os.makedirs(TARGET_DIRS['recent'], exist_ok=True)
        os.makedirs(TARGET_DIRS['automatic'], exist_ok=True)
        os.makedirs(TARGET_DIRS['custom'], exist_ok=True)
        
        print(f"Created target directories at: {os.path.abspath(TARGET_BASE_DIR)}")
        print(f"- LNK Files: {os.path.abspath(TARGET_DIRS['recent'])}")
        print(f"- Automatic Jump Lists: {os.path.abspath(TARGET_DIRS['automatic'])}")
        print(f"- Custom Jump Lists: {os.path.abspath(TARGET_DIRS['custom'])}")
        
        return True
    except Exception as e:
        print(f" [!] Failed to create target directories: {str(e)}")
        return False

def get_user_profiles():
    """Get valid user profiles with robust error handling"""
    users = []
    try:
        for entry in os.listdir(USER_PROFILES_PATH):
            try:
                user_path = os.path.join(USER_PROFILES_PATH, entry)
                if (os.path.isdir(user_path) and 
                    entry not in ["Public", "Default", "Default User", "All Users"] and
                    not entry.startswith('.')):
                    users.append(entry)
            except Exception as e:
                print(f" [!] Error checking user {entry}: {str(e)}")
                continue
        return users
    except Exception as e:
        print(f" [!!!] Failed to access user profiles: {str(e)}")
        return []

def safe_copy(src, dst):
    """Secure file copy with comprehensive checks"""
    try:
        if not os.path.exists(src):
            print(f" [!] Source file does not exist: {src}")
            return False
        if os.path.exists(dst):
            print(f" [!] Destination file already exists: {dst}")
            return False
        shutil.copy2(src, dst)
        print(f" [√] Copied: {src} → {dst}")
        return os.path.exists(dst)
    except Exception as e:
        print(f" [!] Copy failed {src} → {dst}: {str(e)}")
        return False

def detect_artifact_type(file_path):
    """Determine where to store the file based on its type"""
    filename = os.path.basename(file_path).lower()
    if filename.endswith('.lnk'):
        return 'recent'
    elif 'automaticdestinations-ms' in filename:
        return 'automatic'
    elif 'customdestinations-ms' in filename:
        return 'custom'
    return None

def collect_artifacts(source_path, user=None):
    """Collect artifacts and organize them into the appropriate directories"""
    artifacts = {'recent': [], 'automatic': [], 'custom': []}
    
    if not os.path.exists(source_path):
        print(f" [!] Source path does not exist: {source_path}")
        return artifacts
        
    try:
        print(f"\nScanning: {source_path}")
        for root, _, files in os.walk(source_path):
            for file in files:
                src = os.path.join(root, file)
                artifact_type = detect_artifact_type(src)
                
                if artifact_type:
                    prefix = f"{user}_" if user else ""
                    dst = os.path.join(TARGET_DIRS[artifact_type], f"{prefix}{file}")
                    if safe_copy(src, dst):
                        artifacts[artifact_type].append(dst)
                else:
                    print(f" [!] Unknown artifact type: {file}")
    except Exception as e:
        print(f" [!] Error collecting from {source_path}: {str(e)}")
    
    return artifacts

def collect_user_artifacts(user):
    """Collect all artifacts for a specific user"""
    print(f"\n=== Collecting artifacts for user: {user} ===")
    artifacts = {
        'recent': [],
        'automatic': [],
        'custom': []
    }
    
    base_path = os.path.join(USER_PROFILES_PATH, user, "AppData")
    print(f"User AppData path: {base_path}")
    
    # 1. Recent and Jump Lists
    recent_path = os.path.join(base_path, "Roaming", "Microsoft", "Windows", "Recent")
    recent_data = collect_artifacts(recent_path, user)
    artifacts['recent'].extend(recent_data['recent'])
    artifacts['automatic'].extend(recent_data['automatic'])
    artifacts['custom'].extend(recent_data['custom'])
    
    # 2. Desktop shortcuts (LNK files)
    desktop_path = os.path.join(USER_PROFILES_PATH, user, "Desktop")
    desktop_data = collect_artifacts(desktop_path, user)
    artifacts['recent'].extend(desktop_data['recent'])
    
    # 3. Start Menu shortcuts (LNK files)
    start_menu_paths = [
        os.path.join(base_path, "Roaming", "Microsoft", "Windows", "Start Menu"),
        os.path.join(SYSTEM_DRIVE, "ProgramData", "Microsoft", "Windows", "Start Menu")
    ]
    for path in start_menu_paths:
        start_menu_data = collect_artifacts(path, user)
        artifacts['recent'].extend(start_menu_data['recent'])
    
    # 4. Taskbar shortcuts (LNK files)
    taskbar_path = os.path.join(base_path, "Roaming", "Microsoft", "Internet Explorer", "Quick Launch", "User Pinned", "TaskBar")
    taskbar_data = collect_artifacts(taskbar_path, user)
    artifacts['recent'].extend(taskbar_data['recent'])
    
    # 5. Explorer artifacts
    explorer_path = os.path.join(base_path, "Local", "Microsoft", "Windows", "Explorer")
    explorer_data = collect_artifacts(explorer_path, user)
    artifacts['automatic'].extend(explorer_data['automatic'])
    artifacts['custom'].extend(explorer_data['custom'])
    
    return artifacts

def collect_system_artifacts():
    """Collect system-wide artifacts"""
    print("\n=== Collecting system artifacts ===")
    artifacts = {
        'recent': [],
        'automatic': [],
        'custom': []
    }
    
    # 1. Public Desktop (LNK files)
    public_path = os.path.join(USER_PROFILES_PATH, "Public", "Desktop")
    public_data = collect_artifacts(public_path)
    artifacts['recent'].extend(public_data['recent'])
    
    # 2. Recycle Bin (LNK files)
    recycle_path = os.path.join(SYSTEM_DRIVE, "$Recycle.Bin")
    recycle_data = collect_artifacts(recycle_path)
    artifacts['recent'].extend(recycle_data['recent'])
    
    return artifacts

def generate_report(stats):
    """Generate comprehensive collection report"""
    print("\n=== FORENSIC COLLECTION REPORT ===")
    print(f"\nUsers Processed: {stats['users_processed']}")
    
    print("\nArtifacts Collected:")
    print(f"- LNK Files (Recent): {stats['total_recent']}")
    print(f"- Automatic Jump Lists: {stats['total_automatic']}")
    print(f"- Custom Jump Lists: {stats['total_custom']}")
    
    print(f"\nCollection saved to: {os.path.abspath(TARGET_BASE_DIR)}")
    print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

def collect_forensic_artifacts():
    """Main collection function with comprehensive error handling"""
    print("=== Windows LNK Forensic Collector ===")
    print("Initializing collection...")
    
    if not create_target_directories():
        print(" [!!!] Failed to create target directories. Exiting.")
        return
    
    users = get_user_profiles()
    if not users:
        print(" [!!!] No user profiles found. Exiting.")
        return
    
    stats = {
        'users_processed': 0,
        'total_recent': 0,
        'total_automatic': 0,
        'total_custom': 0
    }
    
    # Process user profiles
    for user in users:
        try:
            user_data = collect_user_artifacts(user)
            
            stats['users_processed'] += 1
            stats['total_recent'] += len(user_data['recent'])
            stats['total_automatic'] += len(user_data['automatic'])
            stats['total_custom'] += len(user_data['custom'])
            
            print(f"\nSummary for {user}:")
            print(f"- LNK Files: {len(user_data['recent'])}")
            print(f"- Automatic Jump Lists: {len(user_data['automatic'])}")
            print(f"- Custom Jump Lists: {len(user_data['custom'])}")
            
        except Exception as e:
            print(f" [!!!] Error processing user {user}: {str(e)}")
            continue
    
    # Process system artifacts
    try:
        system_data = collect_system_artifacts()
        stats['total_recent'] += len(system_data['recent'])
        stats['total_automatic'] += len(system_data['automatic'])
        stats['total_custom'] += len(system_data['custom'])
        
        print("\nSystem artifacts summary:")
        print(f"- LNK Files: {len(system_data['recent'])}")
        print(f"- Automatic Jump Lists: {len(system_data['automatic'])}")
        print(f"- Custom Jump Lists: {len(system_data['custom'])}")
        
    except Exception as e:
        print(f" [!!!] Error collecting system artifacts: {str(e)}")
    
    # Generate final report
    generate_report(stats)
    
    return stats

def format_time(timestamp):
    """Format timestamp into readable string"""
    try:
        return datetime.fromtimestamp(int(timestamp)).strftime('%Y-%m-%d %H:%M:%S')
    except ValueError:
        # If timestamp is already in 'YYYY-MM-DDTHH:MM:SS' format
        return datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S').strftime('%Y-%m-%d %H:%M:%S')

def format_size(size):
    """Format file size into human-readable format"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024

def create_database():
    """Create SQLite database with tables for jump list and LNK file data"""
    with sqlite3.connect('LnkDB.db') as conn:
        C = conn.cursor()
        
        # Main jump list table
        C.execute("""
        CREATE TABLE IF NOT EXISTS JLCE (
            Source_Name TEXT,
            Source_Path TEXT,
            Owner_UID INTEGER,
            Owner_GID INTEGER,
            Time_Access TEXT,
            Time_Creation TEXT,
            Time_Modification TEXT,
            AppType TEXT,
            AppID TEXT,
            Artifact TEXT,
            Data_Flags TEXT,
            Local_Path TEXT,  
            Common_Path TEXT,
            Location_Flags TEXT,
            LNK_Class_ID TEXT,
            File_Attributes TEXT,
            FileSize TEXT,
            Header_Size INTEGER,
            IconIndex INTEGER,
            ShowWindow TEXT,
            Drive_Type TEXT,
            Drive_SN TEXT,
            Volume_Label TEXT,
            entry_number TEXT,
            Network_Device_Name TEXT,
            Network_Providers TEXT,
            Network_Share_Flags TEXT,
            Network_Share_Name TEXT,
            Network_Share_Name_uni TEXT,
            File_Permissions TEXT,
            Num_Hard_Links INTEGER,
            Device_ID INTEGER,
            Inode_Number INTEGER
        );
        """)
        
        # Custom jump list table
        C.execute("""
        CREATE TABLE IF NOT EXISTS Custom_JLCE (
            Source_Name TEXT,
            Source_Path TEXT,
            Owner_UID INTEGER,
            Owner_GID INTEGER,
            Time_Access TEXT,
            Time_Creation TEXT,
            Time_Modification TEXT,
            FileSize TEXT,
            File_Permissions TEXT,
            Num_Hard_Links INTEGER,
            Device_ID INTEGER,
            Inode_Number INTEGER,
            Artifact TEXT
        );
        """)
        
        conn.commit()

def detect_artifact(file_path):
    """Detect the type of artifact based on filename"""
    file_name = os.path.basename(file_path)
    if file_name.endswith(".lnk"):
        return "lnk"
    elif "customDestinations-ms" in file_name:
        return "Custom JumpList"
    elif "automaticDestinations-ms" in file_name:
        return "Automatic JumpList"
    else:
        return "Unknown"

def process_custom_jump_list(file_path):
    """Process a custom jump list file and store data in database"""
    try:
        stat_info = os.stat(file_path)
        
        # Collecting relevant statistics
        file_data = {
            'access_time':  format_time(stat_info.st_atime),
            'creation_time': format_time(stat_info.st_ctime),
            'modification_time': format_time(stat_info.st_mtime),
            'file_size': format_size(stat_info.st_size),
            'file_permissions': oct(stat_info.st_mode),
            'owner_uid': stat_info.st_uid,
            'owner_gid': stat_info.st_gid,
            'num_hard_links': stat_info.st_nlink,
            'device_id': stat_info.st_dev,
            'inode_number': stat_info.st_ino,
            'file_name': os.path.basename(file_path),
            'artifact': detect_artifact(file_path),
            'source_name': os.path.basename(file_path),
            'source_path': file_path
        }

        # Manually parse the LNK file
        with open(file_path, 'rb') as f:
            content = f.read()
            header = content[:76]
            lnk_clsid = header[4:20]
            lnk_clsid_str = '-'.join([lnk_clsid[i:i+4].hex() for i in range(0, len(lnk_clsid), 4)])
        
        with sqlite3.connect('LnkDB.db') as conn:
            C = conn.cursor()
            C.execute("""
            INSERT INTO Custom_JLCE (
                Source_Name, Source_Path, Owner_UID, Owner_GID,
                Time_Access, Time_Creation, Time_Modification,
                FileSize, File_Permissions, Num_Hard_Links, Device_ID,
                Inode_Number, Artifact)
            VALUES (
                :source_name, :source_path, :owner_uid, :owner_gid,
                :access_time, :creation_time, :modification_time,
                :file_size, :file_permissions, :num_hard_links, :device_id,
                :inode_number, :artifact)
            """, file_data)
            conn.commit()
        return file_data
    except FileNotFoundError:
        print(f'The file {file_path} does not exist.')
        return None
    except Exception as e:
        print(f'An error occurred processing {file_path}: {e}')
        return None

def process_lnk_and_jump_list_files(folder_path):
    """Process all LNK and jump list files in the specified folder"""
    custom_jump_lists = []
    automatic_jump_lists = []
    lnk_files = []
    unparsed_files = []
    
    # Walk through the directory and collect files by type
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            file_path = os.path.join(root, file)
            artifact_type = detect_artifact(file_path)
            if artifact_type == "lnk":
                lnk_files.append(file_path)
            elif artifact_type == "Custom JumpList":
                custom_jump_lists.append(file_path)
            elif artifact_type == "Automatic JumpList":
                automatic_jump_lists.append(file_path)
    
    # Process each file with Claw(file).CE_dec()
    with sqlite3.connect('LnkDB.db') as conn:
        C = conn.cursor()
        for file in lnk_files + automatic_jump_lists:  # Combine both lists
            try:
                stat_info = os.stat(file)
                Owner_uid = stat_info.st_uid
                owner_gid = stat_info.st_gid
                try:
                    u_l_file = Claw(file).CE_dec()
                    for item in u_l_file:
                        file_permissions = oct(stat_info.st_mode)
                        Source_Name = os.path.basename(file)
                        Source_Path = file
                        Time_Access = item["Time_Access"]
                        Time_Creation = item["Time_Creation"]
                        Time_Modification = item["Time_Modification"]
                        AppType = item["AppType"]
                        AppID = item["AppID"]
                        Artifact = detect_artifact(file)

                        # Insert data into the database
                        C.execute("""
                        INSERT INTO JLCE (
                            Source_Name, Source_Path, Owner_UID, Owner_GID, 
                            Time_Access, Time_Creation, Time_Modification, 
                            AppType, AppID, Artifact, Data_Flags, Local_Path, 
                            Common_Path, Location_Flags, LNK_Class_ID, File_Attributes, 
                            FileSize, Header_Size, IconIndex, ShowWindow, 
                            Drive_Type, Drive_SN, Volume_Label, entry_number, 
                            Network_Device_Name, Network_Providers, Network_Share_Flags, 
                            Network_Share_Name, Network_Share_Name_uni, File_Permissions, 
                            Num_Hard_Links, Device_ID, Inode_Number)
                        VALUES (
                            :Source_Name, :Source_Path, :Owner_UID, :Owner_GID, 
                            :Time_Access, :Time_Creation, :Time_Modification, 
                            :AppType, :AppID, :Artifact, :Data_Flags, :Local_Path, 
                            :Common_Path, :Location_Flags, :LNK_Class_ID, :File_Attributes, 
                            :FileSize, :Header_Size, :IconIndex, :ShowWindow, 
                            :Drive_Type, :Drive_SN, :Volume_Label, :entry_number, 
                            :Network_Device_Name, :Network_Providers, :Network_Share_Flags, 
                            :Network_Share_Name, :Network_Share_Name_uni, :File_Permissions, 
                            :Num_Hard_Links, :Device_ID, :Inode_Number)
                        """, {
                            "Source_Name": Source_Name,
                            "Source_Path": Source_Path,
                            "Owner_UID": Owner_uid,
                            "Owner_GID": owner_gid,
                            "Time_Access": Time_Access,
                            "Time_Creation": Time_Creation,
                            "Time_Modification": Time_Modification,
                            "AppType": AppType,
                            "AppID": AppID,
                            "Artifact": Artifact,
                            "Data_Flags": item.get("Data_Flags"),
                            "Local_Path": item.get("Local_Path"),
                            "Common_Path": item.get("Common_Path"),
                            "Location_Flags": item.get("Location_Flags"),
                            "LNK_Class_ID": item.get("LNK_Class_ID"),
                            "File_Attributes": item.get("File_Attributes"),
                            "FileSize": format_size(stat_info.st_size),
                            "Header_Size": item.get("Header_Size"),
                            "IconIndex": item.get("IconIndex"),
                            "ShowWindow": item.get("ShowWindow"),
                            "Drive_Type": item.get("Drive_Type"),
                            "Drive_SN": item.get("Drive_SN"),
                            "Volume_Label": item.get("Volume_Label"),
                            "entry_number": item.get("entry_number"),
                            "Network_Device_Name": item.get("Network_Device_Name"),
                            "Network_Providers": item.get("Network_Providers"),
                            "Network_Share_Flags": item.get("Network_Share_Flags"),
                            "Network_Share_Name": item.get("Network_Share_Name"),
                            "Network_Share_Name_uni": item.get("Network_Share_Name_uni"),
                            "File_Permissions": file_permissions,
                            "Num_Hard_Links": stat_info.st_nlink,
                            "Device_ID": stat_info.st_dev,
                            "Inode_Number": stat_info.st_ino
                        })
                        conn.commit()
                except Exception as e:
                    print(f'Error processing file {file}: {e}')
                    unparsed_files.append(file)
            except FileNotFoundError:
                print(f'The file {file} does not exist.')
                unparsed_files.append(file)
    
    # Process custom jump lists
    for CJL in custom_jump_lists:
        process_custom_jump_list(CJL)
    
    return {
        "custom_jump_lists": custom_jump_lists,
        "automatic_jump_lists": automatic_jump_lists,
        "lnk_files": lnk_files,
        "unparsed_files": unparsed_files
    }

def print_database_content(db_file):
    """Print the contents of the database for verification"""
    try:
        with sqlite3.connect(db_file) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM JLCE")
            rows = cursor.fetchall()
            for row in rows:
                print(row)
    except Exception as e:
        print(f'An error occurred while reading the database: {e}')

def  A_CJL_LNK_Claw():
    """Main execution function"""
    try:
        # First collect all forensic artifacts
        collection_stats = collect_forensic_artifacts()
        
        # Then process the collected files into the database
        folder_path = "Artifacts_Collectors/Target Artifacts/C,AJL and LNK/Recent"
        create_database()
        file_stats = process_lnk_and_jump_list_files(folder_path)
        
        # Print results
        print("\n=== PROCESSING RESULTS ===")
        print("Custom Jump Lists:", file_stats["custom_jump_lists"])
        print("Automatic Jump Lists:", file_stats["automatic_jump_lists"])
        print("LNK Files:", file_stats["lnk_files"])
        print("Unparsed files:", file_stats["unparsed_files"])
        
        # Print database content for verification
        print("\nDatabase content:")
        print_database_content('LnkDB.db')
        
    except KeyboardInterrupt:
        print("\nCollection aborted by user.")
    except Exception as e:
        print(f"\n [!!!] Critical error: {str(e)}")

    print("\033[92m\nParsing automatic,custom jumplist and LNK files has been completed by Crow Eye\033[0m")
if __name__ == "__main__":
    A_CJL_LNK_Claw()