import os
import sys
# Add the parent directory to sys.path first, then import Claw
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from Artifacts_Collectors.JLParser import Claw
import sqlite3
from datetime import datetime
import shutil
import struct

def safe_sqlite_int(value):
    """Safely handle large integer values for SQLite insertion"""
    try:
        if value is None:
            return None
        if isinstance(value, str):
            value = int(value)
        return value if abs(value) <= 2**63-1 else None
    except (ValueError, TypeError):
        return None

# Configure target directory structure
TARGET_BASE_DIR = os.path.join("Artifacts_Collectors", "Target Artifacts", "C,AJL and LNK")
TARGET_DIRS = {
    'recent': os.path.join(TARGET_BASE_DIR, "Recent"),  # For LNK files
    'automatic': os.path.join(TARGET_BASE_DIR, "Recent", "AutomaticDestinations"),  # For automatic jump lists
    'custom': os.path.join(TARGET_BASE_DIR, "Recent", "CustomDestinations")  # For custom jump lists
}

def update_target_directories(case_path=None):
    """Update target directories based on case path if provided"""
    global TARGET_BASE_DIR, TARGET_DIRS
    
    if case_path:
        # If case path is provided, update the target directories
        TARGET_BASE_DIR = os.path.join(case_path, "Target_Artifacts", "C_AJL_Lnk")
        TARGET_DIRS = {
            'recent': os.path.join(TARGET_BASE_DIR, "Recent"),  # For LNK files
            'automatic': os.path.join(TARGET_BASE_DIR, "Recent", "AutomaticDestinations"),  # For automatic jump lists
            'custom': os.path.join(TARGET_BASE_DIR, "Recent", "CustomDestinations")  # For custom jump lists
        }
        print(f"Using case path for artifacts: {TARGET_BASE_DIR}")
    else:
        # Use default paths
        TARGET_BASE_DIR = os.path.join("Artifacts_Collectors", "Target Artifacts", "C,AJL and LNK")
        TARGET_DIRS = {
            'recent': os.path.join(TARGET_BASE_DIR, "Recent"),  # For LNK files
            'automatic': os.path.join(TARGET_BASE_DIR, "Recent", "AutomaticDestinations"),  # For automatic jump lists
            'custom': os.path.join(TARGET_BASE_DIR, "Recent", "CustomDestinations")  # For custom jump lists
        }
    
    return TARGET_DIRS


# System configuration
SYSTEM_DRIVE = os.environ["SystemDrive"] + "\\"  
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

def detect_artifact(file_path):
    """Detect the type of artifact based on file extension and name"""
    filename = os.path.basename(file_path).lower()
    
    if filename.endswith('.lnk'):
        return "lnk"
    elif "automaticdestinations-ms" in filename:
        return "Automatic JumpList"
    elif "customdestinations-ms" in filename:
        return "Custom JumpList"
    else:
        return "Unknown"

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
                artifact_type = detect_artifact(src)
                
                # Map the artifact type to the directory key
                dir_key = None
                if artifact_type == "lnk":
                    dir_key = "recent"
                elif artifact_type == "Automatic JumpList":
                    dir_key = "automatic"
                elif artifact_type == "Custom JumpList":
                    dir_key = "custom"
                
                if dir_key:
                    prefix = f"{user}_" if user else ""
                    dst = os.path.join(TARGET_DIRS[dir_key], f"{prefix}{file}")
                    if safe_copy(src, dst):
                        artifacts[dir_key].append(dst)
                # Remove the print for unknown artifact types
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

def windows_filetime_to_unix(filetime):
    """Convert Windows FILETIME to Unix timestamp"""
    try:
        # Windows FILETIME epoch starts January 1, 1601
        # Unix epoch starts January 1, 1970
        # Difference is 11644473600 seconds
        FILETIME_EPOCH_DIFF = 11644473600
        
        if isinstance(filetime, int):
            # Convert from 100-nanosecond intervals to seconds
            unix_timestamp = (filetime / 10000000.0) - FILETIME_EPOCH_DIFF
            return unix_timestamp
        return None
    except (ValueError, TypeError, OverflowError):
        return None

def format_time(timestamp):
    """Format timestamp into readable string with robust error handling"""
    try:
        # Handle None or empty values
        if timestamp is None or timestamp == "":
            return "N/A"
        
        # Handle string timestamps
        if isinstance(timestamp, str):
            # Try to parse ISO format first
            try:
                return datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S').strftime('%Y-%m-%d %H:%M:%S')
            except ValueError:
                try:
                    # Try to parse as integer string
                    timestamp = int(timestamp)
                except ValueError:
                    return timestamp  # Return as-is if can't parse
        
        # Handle integer timestamps
        if isinstance(timestamp, int):
            # Check if it's a Windows FILETIME (very large number)
            if timestamp > 10000000000000000:  # Likely Windows FILETIME
                unix_timestamp = windows_filetime_to_unix(timestamp)
                if unix_timestamp:
                    timestamp = unix_timestamp
                else:
                    return "Invalid FILETIME"
            
            # Check if timestamp is too large for datetime
            if timestamp > 2147483647:  # Unix timestamp limit for 32-bit systems
                # Try to handle as 64-bit timestamp
                try:
                    return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
                except (ValueError, OSError, OverflowError):
                    # If still too large, try to convert from microseconds or nanoseconds
                    for divisor in [1000, 1000000, 1000000000]:
                        try:
                            adjusted_timestamp = timestamp / divisor
                            if 0 < adjusted_timestamp < 2147483647:
                                return datetime.fromtimestamp(adjusted_timestamp).strftime('%Y-%m-%d %H:%M:%S')
                        except (ValueError, OSError, OverflowError):
                            continue
                    return f"Timestamp too large: {timestamp}"
            else:
                return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
        
        # Handle float timestamps
        if isinstance(timestamp, float):
            try:
                return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
            except (ValueError, OSError, OverflowError):
                return f"Invalid timestamp: {timestamp}"
        
        # If we get here, return the original value as string
        return str(timestamp)
        
    except Exception as e:
        print(f"Error formatting timestamp {timestamp}: {e}")
        return f"Error: {timestamp}"

def format_size(size):
    """Format file size into human-readable format"""
    try:
        size = float(size)
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} PB"
    except (ValueError, TypeError):
        return str(size)

def create_database(case_path=None):
    """Create SQLite database with tables for jump list and LNK file data"""
    # Set the database path
    db_path = 'LnkDB.db'  # Default path
    if case_path:
        # If a case path is provided, use it for the database
        artifacts_dir = os.path.join(case_path, 'Target_Artifacts')
        if os.path.exists(artifacts_dir):
            db_path = os.path.join(artifacts_dir, 'LnkDB.db')
            print(f"Using case path for database: {db_path}")
    
    with sqlite3.connect(db_path) as conn:
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
    
    return db_path

def process_custom_jump_list(file_path, db_path='LnkDB.db'):
    """Process a custom jump list file and store data in database"""
    try:
        stat_info = os.stat(file_path)
        
        # Collecting relevant statistics with safe timestamp formatting
        file_data = {
            'access_time': format_time(stat_info.st_atime),
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

        with sqlite3.connect(db_path) as conn:
            C = conn.cursor()
            C.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Custom_JLCE'")
            if not C.fetchone():
                print("Creating Custom_JLCE table as it doesn't exist")
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
            
            # Insert the data using parameter binding for safety
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
            """, {
                "source_name": file_data['source_name'],
                "source_path": file_data['source_path'],
                "owner_uid": safe_sqlite_int(file_data['owner_uid']),
                "owner_gid": safe_sqlite_int(file_data['owner_gid']),
                "access_time": file_data['access_time'],
                "creation_time": file_data['creation_time'],
                "modification_time": file_data['modification_time'],
                "file_size": file_data['file_size'],
                "file_permissions": file_data['file_permissions'],
                "num_hard_links": safe_sqlite_int(file_data['num_hard_links']),
                "device_id": safe_sqlite_int(file_data['device_id']),
                "inode_number": safe_sqlite_int(file_data['inode_number']),
                "artifact": file_data['artifact']
            })
            
            conn.commit()
            print(f"Successfully added custom jump list to database: {file_path}")
        
        return file_data
    except FileNotFoundError:
        print(f'The file {file_path} does not exist.')
        return None
    except Exception as e:
        print(f'An error occurred processing {file_path}: {e}')
        import traceback
        traceback.print_exc()
        return None

def process_lnk_and_jump_list_files(folder_path, db_path='LnkDB.db'):
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
    with sqlite3.connect(db_path) as conn:
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
                        # Use safe timestamp formatting
                        Time_Access = format_time(item.get("Time_Access"))
                        Time_Creation = format_time(item.get("Time_Creation"))
                        Time_Modification = format_time(item.get("Time_Modification"))
                        AppType = item.get("AppType", "")
                        AppID = item.get("AppID", "")
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
                            "Owner_UID": safe_sqlite_int(Owner_uid),
                            "Owner_GID": safe_sqlite_int(owner_gid),
                            "Time_Access": Time_Access,
                            "Time_Creation": Time_Creation,
                            "Time_Modification": Time_Modification,
                            "AppType": AppType,
                            "AppID": AppID,
                            "Artifact": Artifact,
                            "Data_Flags": item.get("Data_Flags", ""),
                            "Local_Path": item.get("Local_Path", ""),
                            "Common_Path": item.get("Common_Path", ""),
                            "Location_Flags": item.get("Location_Flags", ""),
                            "LNK_Class_ID": item.get("LNK_Class_ID", ""),
                            "File_Attributes": item.get("File_Attributes", ""),
                            "FileSize": format_size(stat_info.st_size),
                            "Header_Size": safe_sqlite_int(item.get("Header_Size")),
                            "IconIndex": safe_sqlite_int(item.get("IconIndex")),
                            "ShowWindow": item.get("ShowWindow", ""),
                            "Drive_Type": item.get("Drive_Type", ""),
                            "Drive_SN": item.get("Drive_SN", ""),
                            "Volume_Label": item.get("Volume_Label", ""),
                            "entry_number": item.get("entry_number", ""),
                            "Network_Device_Name": item.get("Network_Device_Name", ""),
                            "Network_Providers": item.get("Network_Providers", ""),
                            "Network_Share_Flags": item.get("Network_Share_Flags", ""),
                            "Network_Share_Name": item.get("Network_Share_Name", ""),
                            "Network_Share_Name_uni": item.get("Network_Share_Name_uni", ""),
                            "File_Permissions": file_permissions,
                            "Num_Hard_Links": safe_sqlite_int(stat_info.st_nlink),
                            "Device_ID": safe_sqlite_int(stat_info.st_dev),
                            "Inode_Number": safe_sqlite_int(stat_info.st_ino)
                        })
                        conn.commit()
                        print(f"Successfully processed: {file}")
                except Exception as e:
                    print(f'Error processing file {file}: {e}')
                    unparsed_files.append(file)
            except FileNotFoundError:
                print(f'The file {file} does not exist.')
                unparsed_files.append(file)
            except Exception as e:
                print(f'Error accessing file {file}: {e}')
                unparsed_files.append(file)
    
    # Process custom jump lists
    print(f"Processing {len(custom_jump_lists)} custom jump lists")
    for file in custom_jump_lists:
        try:
            print(f"Processing custom jump list: {file}")
            result = process_custom_jump_list(file, db_path)
            if result:
                print(f"Successfully processed custom jump list: {file}")
            else:
                print(f"Failed to process custom jump list: {file}")
                unparsed_files.append(file)
        except Exception as e:
            print(f"Error processing custom jump list: {file} - {str(e)}")
            unparsed_files.append(file)

    return len(unparsed_files)

def A_CJL_LNK_Claw(case_path=None, offline_mode=False):
    """Main execution function"""
    db_path = None  # Initialize db_path to avoid UnboundLocalError
    
    try:
        # Update target directories based on case path
        update_target_directories(case_path)
        
        if not offline_mode:
            # Normal mode - collect artifacts from the live system
            collection_stats = collect_forensic_artifacts()
            print("\n=== COLLECTION RESULTS ===")
            # Fix: Use the correct dictionary keys from collect_forensic_artifacts
            print(f"LNK Files: {collection_stats['total_recent']}")
            print(f"Automatic Jump Lists: {collection_stats['total_automatic']}")
            print(f"Custom Jump Lists: {collection_stats['total_custom']}")
        else:
            # Offline mode - process artifacts from the case directory
            print("\n=== OFFLINE MODE ===")
            print("Processing artifacts from case directory")
            # No collection needed, files should already be in the target directories
            
        # Create database with case path
        db_path = create_database(case_path)
        
        # Then process the collected files into the database
        folder_path = TARGET_BASE_DIR  # Process the entire target directory
        if not os.path.exists(folder_path):
            print(f"Creating folder path: {folder_path}")
            os.makedirs(folder_path, exist_ok=True)
            
        print(f"Processing files from: {folder_path}")
        # Process files and collect statistics
        custom_jump_lists = []
        automatic_jump_lists = []
        lnk_files = []
        
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
        
        # Process the files
        unparsed_count = process_lnk_and_jump_list_files(folder_path, db_path)
        
        # Create file_stats dictionary
        file_stats = {
            "custom_jump_lists": len(custom_jump_lists),
            "automatic_jump_lists": len(automatic_jump_lists),
            "lnk_files": len(lnk_files),
            "unparsed_files": unparsed_count
        }
        
        # Print results
        print("\n=== PROCESSING RESULTS ===")
        print(f"Custom Jump Lists: {file_stats['custom_jump_lists']}")
        print(f"Automatic Jump Lists: {file_stats['automatic_jump_lists']}")
        print(f"LNK Files: {file_stats['lnk_files']}")
        print(f"Unparsed files: {file_stats['unparsed_files']}")
        
    except KeyboardInterrupt:
        print("\nCollection aborted by user.")
    except Exception as e:
        print(f"\n [!!!] Critical error: {str(e)}")
        import traceback
        traceback.print_exc()

    print(f"\033[92m\nParsing automatic,custom jumplist and LNK files has been completed by Crow Eye\nDatabase saved to: {db_path}\033[0m")

if __name__ == "__main__":
    A_CJL_LNK_Claw()
