import os
import sys
# Add the parent directory to sys.path first, then import Claw
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from Artifacts_Collectors.JLParser import Claw
import sqlite3
from datetime import datetime
import shutil
import struct

# Constants for magic numbers
FILETIME_THRESHOLD = 10000000000000000  # Threshold for Windows FILETIME detection
UNIX_TIMESTAMP_LIMIT = 2147483647       # Unix timestamp limit for 32-bit systems


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
        return None  # Return None instead of "Unknown" for non-LNK/JL files

def collect_artifacts(source_path, user=None):
    """Collect artifacts and organize them into the appropriate directories"""
    artifacts = {'recent': [], 'automatic': [], 'custom': []}
    
    if not os.path.exists(source_path):
        # Only print error for important paths, not for every missing directory
        if is_important_path(source_path):
            print(f" [!] Source path does not exist: {source_path}")
        return artifacts
        
    try:
        # Only print scanning message for important paths
        # Note: Only LNK and Jump List files will be processed, others will be silently ignored
        # This message indicates we're scanning the directory, not that we're processing non-LNK files
        if is_important_path(source_path):
            print(f"Scanning directory for LNK/JL files (non-LNK/JL files will be silently ignored): {source_path}")
            
        # Use the new reusable function to categorize files
        lnk_files, automatic_jump_lists, custom_jump_lists = categorize_files_by_type(source_path)
        
        # Process all categorized files
        all_files = [(lnk_files, "recent"), (automatic_jump_lists, "automatic"), (custom_jump_lists, "custom")]
        
        for file_list, dir_key in all_files:
            for file in file_list:
                src = file
                artifact_type = detect_artifact(src)
                
                if artifact_type:
                    prefix = f"{user}_" if user else ""
                    dst = os.path.join(TARGET_DIRS[dir_key], f"{prefix}{os.path.basename(file)}")
                    if safe_copy(src, dst):
                        artifacts[dir_key].append(dst)
                        print_success_message(f" [√] Copied: {src} → {dst}", source_path, artifact_type)
                # Silently ignore unknown file types
    except Exception as e:
        # Only print error for important paths
        # Note: This is for the entire directory scanning process, not individual files
        if is_important_path(source_path):
            print(f" [!] Error scanning directory {source_path}: {str(e)}")
    
    return artifacts

def parse_artifacts_directly(source_path, db_path, user=None):
    """Parse artifacts directly without copying them"""
    artifacts = {'recent': [], 'automatic': [], 'custom': []}
    unparsed_files = []
    
    if not os.path.exists(source_path):
        # Only print error for important paths
        if is_important_path(source_path):
            print(f" [!] Source path does not exist: {source_path}")
        return artifacts, unparsed_files
        
    try:
        # Only print scanning message for important paths
        # Note: Only LNK and Jump List files will be processed, others will be silently ignored
        # This message indicates we're scanning the directory, not that we're processing non-LNK files
        if is_important_path(source_path):
            print(f"Scanning and parsing LNK/JL files (non-LNK/JL files will be silently ignored): {source_path}")
            
        with sqlite3.connect(db_path) as conn:
            C = conn.cursor()
            
            # Use the new reusable function to categorize files
            lnk_files, automatic_jump_lists, custom_jump_lists = categorize_files_by_type(source_path)
            
            # Process LNK and Automatic JumpList files
            for file in lnk_files + automatic_jump_lists:
                src = file
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
                    try:
                        # Process with Claw parser
                        stat_info = os.stat(src)
                        Owner_uid = stat_info.st_uid
                        owner_gid = stat_info.st_gid
                        
                        try:
                            u_l_file = Claw(src).CE_dec()
                            # Debug: Check if parsing returned any results
                            if not u_l_file:
                                print(f"Debug: No data returned from parsing {src}")
                            else:
                                print(f"Debug: Parsed {len(u_l_file)} items from {src}")
                        except Exception as parse_error:
                            print(f"Debug: Error parsing {src}: {parse_error}")
                            import traceback
                            traceback.print_exc()
                            u_l_file = []
                        
                        # Check if we have any items to process
                        if not u_l_file:
                            warning_msg = f"Warning: No items parsed from {src} - this file may be corrupted, unsupported, or inaccessible"
                            print(warning_msg)
                            unparsed_files.append(src)
                            continue
                        
                        for item in u_l_file:
                            # Use reusable function for database insertion
                            if insert_lnk_data_to_db(C, src, item, stat_info, artifact_type):
                                conn.commit()
                                print_success_message(f"Successfully processed: {src}", source_path, artifact_type)
                                artifacts[dir_key].append(src)
                            else:
                                error_msg = f"Failed to insert data for: {src}"
                                print_error_message(error_msg, source_path)
                                unparsed_files.append(src)
                                
                    except Exception as e:
                        # Only print error for important paths and LNK/JL files
                        error_msg = f'Error processing file {src}: {e}'
                        print_error_message(error_msg, source_path, artifact_type)
                        unparsed_files.append(src)
            
            # Process Custom JumpList files
            for file in custom_jump_lists:
                src = file
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
                    try:
                        # Process custom jump list
                        stat_info = os.stat(src)
                        
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
                            'file_name': os.path.basename(src),
                            'artifact': artifact_type,
                            'source_name': os.path.basename(src),
                            'source_path': src
                        }
                        
                        # Use reusable function for database insertion
                        if insert_custom_jl_data_to_db(C, file_data):
                            conn.commit()
                            print_success_message(f"Successfully processed custom jump list: {src}", source_path, artifact_type)
                            artifacts[dir_key].append(src)
                        else:
                            error_msg = f"Failed to insert custom jump list data for: {src}"
                            print_error_message(error_msg, source_path)
                            unparsed_files.append(src)
                            
                    except Exception as e:
                        # Only print error for important paths and LNK/JL files
                        error_msg = f'Error processing custom jump list {src}: {e}'
                        print_error_message(error_msg, source_path, artifact_type)
                        unparsed_files.append(src)
                        
    except Exception as e:
        # Only print error for important paths
        # Note: This is for the entire directory scanning process, not individual files
        if is_important_path(source_path):
            print(f" [!] Error scanning directory for parsing {source_path}: {str(e)}")
    
    return artifacts, unparsed_files

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

def parse_user_artifacts_directly(user, db_path):
    """Parse all artifacts for a specific user directly without copying"""
    print(f"\n=== Parsing artifacts for user: {user} ===")
    artifacts = {
        'recent': [],
        'automatic': [],
        'custom': []
    }
    unparsed_files = []
    
    base_path = os.path.join(USER_PROFILES_PATH, user, "AppData")
    print(f"User AppData path: {base_path}")
    
    # 1. Recent and Jump Lists
    recent_path = os.path.join(base_path, "Roaming", "Microsoft", "Windows", "Recent")
    recent_data, recent_unparsed = parse_artifacts_directly(recent_path, db_path, user)
    artifacts['recent'].extend(recent_data['recent'])
    artifacts['automatic'].extend(recent_data['automatic'])
    artifacts['custom'].extend(recent_data['custom'])
    unparsed_files.extend(recent_unparsed)
    
    # 2. Desktop shortcuts (LNK files)
    desktop_path = os.path.join(USER_PROFILES_PATH, user, "Desktop")
    desktop_data, desktop_unparsed = parse_artifacts_directly(desktop_path, db_path, user)
    artifacts['recent'].extend(desktop_data['recent'])
    unparsed_files.extend(desktop_unparsed)
    
    # 3. Start Menu shortcuts (LNK files)
    start_menu_paths = [
        os.path.join(base_path, "Roaming", "Microsoft", "Windows", "Start Menu"),
        os.path.join(SYSTEM_DRIVE, "ProgramData", "Microsoft", "Windows", "Start Menu")
    ]
    for path in start_menu_paths:
        start_menu_data, start_menu_unparsed = parse_artifacts_directly(path, db_path, user)
        artifacts['recent'].extend(start_menu_data['recent'])
        unparsed_files.extend(start_menu_unparsed)
    
    # 4. Taskbar shortcuts (LNK files)
    taskbar_path = os.path.join(base_path, "Roaming", "Microsoft", "Internet Explorer", "Quick Launch", "User Pinned", "TaskBar")
    taskbar_data, taskbar_unparsed = parse_artifacts_directly(taskbar_path, db_path, user)
    artifacts['recent'].extend(taskbar_data['recent'])
    unparsed_files.extend(taskbar_unparsed)
    
    # 5. Explorer artifacts
    explorer_path = os.path.join(base_path, "Local", "Microsoft", "Windows", "Explorer")
    explorer_data, explorer_unparsed = parse_artifacts_directly(explorer_path, db_path, user)
    artifacts['automatic'].extend(explorer_data['automatic'])
    artifacts['custom'].extend(explorer_data['custom'])
    unparsed_files.extend(explorer_unparsed)
    
    return artifacts, unparsed_files

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

def parse_system_artifacts_directly(db_path):
    """Parse system-wide artifacts directly without copying"""
    print("\n=== Parsing system-wide artifacts ===")
    artifacts = {
        'recent': [],
        'automatic': [],
        'custom': []
    }
    unparsed_files = []
    
    # 1. Public Desktop shortcuts
    public_desktop_path = os.path.join(SYSTEM_DRIVE, "Users", "Public", "Desktop")
    public_desktop_data, public_desktop_unparsed = parse_artifacts_directly(public_desktop_path, db_path, "Public")
    artifacts['recent'].extend(public_desktop_data['recent'])
    unparsed_files.extend(public_desktop_unparsed)
    
    # 2. Recycle Bin
    recycle_bin_path = os.path.join(SYSTEM_DRIVE, "$Recycle.Bin")
    if os.path.exists(recycle_bin_path):
        for sid_folder in os.listdir(recycle_bin_path):
            sid_path = os.path.join(recycle_bin_path, sid_folder)
            if os.path.isdir(sid_path):
                recycle_bin_data, recycle_bin_unparsed = parse_artifacts_directly(sid_path, db_path, f"RecycleBin_{sid_folder}")
                artifacts['recent'].extend(recycle_bin_data['recent'])
                unparsed_files.extend(recycle_bin_unparsed)
    
    return artifacts, unparsed_files

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
            print("  Note: Only LNK and Jump List files are processed. Other files in these directories are silently ignored.")
            
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
        print("  Note: Only LNK and Jump List files are processed. Other files in these directories are silently ignored.")
        
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
            if timestamp > FILETIME_THRESHOLD:  # Likely Windows FILETIME
                unix_timestamp = windows_filetime_to_unix(timestamp)
                if unix_timestamp:
                    timestamp = unix_timestamp
                else:
                    return "Invalid FILETIME"
            
            # Check if timestamp is too large for datetime
            if timestamp > UNIX_TIMESTAMP_LIMIT:  # Unix timestamp limit for 32-bit systems
                # Try to handle as 64-bit timestamp
                try:
                    return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
                except (ValueError, OSError, OverflowError):
                    # If still too large, try to convert from microseconds or nanoseconds
                    for divisor in [1000, 1000000, 1000000000]:
                        try:
                            adjusted_timestamp = timestamp / divisor
                            if 0 < adjusted_timestamp < UNIX_TIMESTAMP_LIMIT:
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
    unparsed_files = []
    
    # Categorize files by type using reusable function
    lnk_files, automatic_jump_lists, custom_jump_lists = categorize_files_by_type(folder_path)
    
    # Collect and print processing statistics using reusable function
    stats = collect_processing_statistics(lnk_files, automatic_jump_lists, custom_jump_lists)
    print_processing_summary(stats, folder_path)
    
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
                    # Debug: Check if parsing returned any results
                    if not u_l_file:
                        print(f"Debug: No data returned from parsing {file}")
                    else:
                        print(f"Debug: Parsed {len(u_l_file)} items from {file}")
                    
                    # Check if we have any items to process
                    if not u_l_file:
                        print(f"Warning: No items parsed from {file} - this file may be corrupted or unsupported")
                        unparsed_files.append(file)
                        continue
                        
                    for item in u_l_file:
                        # Use reusable function for database insertion
                        if insert_lnk_data_to_db(C, file, item, stat_info, detect_artifact(file)):
                            conn.commit()
                            print_success_message(f"Successfully processed: {file}", file, detect_artifact(file))
                        else:
                            print_error_message(f"Failed to insert data for: {file}", file)
                except Exception as e:
                    error_msg = f'Error processing file {file}: {e}'
                    print_error_message(error_msg, file)
                    import traceback
                    traceback.print_exc()
                    unparsed_files.append(file)
            except FileNotFoundError:
                error_msg = f'The file {file} does not exist.'
                print_error_message(error_msg, file)
                unparsed_files.append(file)
            except Exception as e:
                error_msg = f'Error accessing file {file}: {e}'
                print_error_message(error_msg, file)
                unparsed_files.append(file)
    
    # Process custom jump lists
    if custom_jump_lists:
        print(f"Processing {len(custom_jump_lists)} custom jump lists")
        for file in custom_jump_lists:
            try:
                print(f"Processing custom jump list: {file}")
                result = process_custom_jump_list(file, db_path)
                if result:
                    print_success_message(f"Successfully processed custom jump list: {file}", file, "Custom JumpList")
                else:
                    error_msg = f"Failed to process custom jump list: {file}"
                    print_error_message(error_msg, file)
                    unparsed_files.append(file)
            except Exception as e:
                error_msg = f"Error processing custom jump list: {file} - {str(e)}"
                print_error_message(error_msg, file)
                unparsed_files.append(file)

    return len(unparsed_files)

def is_important_path(source_path):
    """Check if the path is considered important for detailed messaging"""
    return ("Recent" in source_path or "Desktop" in source_path or 
            "Start Menu" in source_path or "Explorer" in source_path)

def print_success_message(message, source_path=None, artifact_type=None):
    """Print success messages with consistent conditional logic"""
    if source_path is None or is_important_path(source_path):
        if artifact_type is None or artifact_type:
            print(message)

def print_error_message(message, source_path=None, artifact_type=None):
    """Print error messages with consistent conditional logic"""
    if source_path is None or is_important_path(source_path):
        if artifact_type is None or artifact_type:
            print(message)

def categorize_files_by_type(folder_path):
    """Walk through directory and categorize files by artifact type"""
    custom_jump_lists = []
    automatic_jump_lists = []
    lnk_files = []
    
    # Walk through the directory and collect files by type
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            file_path = os.path.join(root, file)
            artifact_type = detect_artifact(file_path)
            # Only collect LNK and Jump List files
            if artifact_type == "lnk":
                lnk_files.append(file_path)
            elif artifact_type == "Custom JumpList":
                custom_jump_lists.append(file_path)
            elif artifact_type == "Automatic JumpList":
                automatic_jump_lists.append(file_path)
            # Silently ignore other file types
    
    return lnk_files, automatic_jump_lists, custom_jump_lists

def collect_processing_statistics(lnk_files, automatic_jump_lists, custom_jump_lists):
    """Collect and return processing statistics"""
    return {
        "lnk_files": len(lnk_files),
        "automatic_jump_lists": len(automatic_jump_lists),
        "custom_jump_lists": len(custom_jump_lists),
        "total_files": len(lnk_files) + len(automatic_jump_lists) + len(custom_jump_lists)
    }

def print_processing_summary(stats, source_description="directory"):
    """Print a consistent processing summary"""
    if stats["total_files"] > 0:
        print(f"Processing {stats['lnk_files']} LNK files, "
              f"{stats['automatic_jump_lists']} Automatic Jump Lists, "
              f"and {stats['custom_jump_lists']} Custom Jump Lists from {source_description}")
        print("  Note: Only LNK and Jump List files are processed. Other files in these directories are silently ignored.")

def insert_lnk_data_to_db(cursor, source_path, item, stat_info, artifact_type):
    """Insert LNK file data into the database"""
    try:
        file_permissions = oct(stat_info.st_mode)
        source_name = os.path.basename(source_path)
        source_path_full = source_path
        
        # Use safe timestamp formatting
        time_access = format_time(item.get("Time_Access"))
        time_creation = format_time(item.get("Time_Creation"))
        time_modification = format_time(item.get("Time_Modification"))
        app_type = item.get("AppType", "")
        app_id = item.get("AppID", "")
        artifact = artifact_type

        # Insert data into the database
        cursor.execute("""
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
            "Source_Name": source_name,
            "Source_Path": source_path_full,
            "Owner_UID": safe_sqlite_int(stat_info.st_uid),
            "Owner_GID": safe_sqlite_int(stat_info.st_gid),
            "Time_Access": time_access,
            "Time_Creation": time_creation,
            "Time_Modification": time_modification,
            "AppType": app_type,
            "AppID": app_id,
            "Artifact": artifact,
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
        return True
    except Exception as e:
        print(f"Error inserting LNK data to database: {e}")
        return False

def insert_custom_jl_data_to_db(cursor, file_data):
    """Insert Custom Jump List data into the database"""
    try:
        # Insert the data using parameter binding for safety
        cursor.execute("""
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
        return True
    except Exception as e:
        print(f"Error inserting Custom Jump List data to database: {e}")
        return False

def A_CJL_LNK_Claw(case_path=None, offline_mode=False, direct_parse=True):
    """
    Main execution function for LNK and Jump List artifact collection and parsing.
    
    This function orchestrates the collection and parsing of Windows LNK files and Jump List artifacts,
    storing the extracted data in a SQLite database for forensic analysis.
    
    DIRECT PARSING MODE (DEFAULT):
    - Files are parsed directly from their original locations
    - No copying of files to preserve original metadata and timestamps
    - More efficient as it avoids unnecessary file operations
    - Preserves file access times and other forensic artifacts
    
    Args:
        case_path (str, optional): Path to case directory. Defaults to None.
        offline_mode (bool, optional): Whether to run in offline mode (processes existing collected files). Defaults to False.
        direct_parse (bool, optional): Whether to parse artifacts directly without copying (recommended). Defaults to True.
        
    Process Flow:
        1. Update target directories based on case path
        2. Create database with appropriate schema
        3. Based on mode:
           - Direct parse (default): Parse artifacts directly from user profiles
           - Normal mode: Collect artifacts from live system then parse
           - Offline mode: Parse artifacts from existing case directory
        4. Store parsed data in SQLite database
        5. Report results and statistics
        
    Returns:
        str: Path to the database file containing parsed artifacts, or None if an error occurred
    """
    db_path = None  # Initialize db_path to avoid UnboundLocalError
    
    try:
        # Update target directories based on case path
        update_target_directories(case_path)
        
        # Create database with case path
        db_path = create_database(case_path)
        
        if direct_parse:
            # Direct parsing mode - parse artifacts directly without copying (DEFAULT BEHAVIOR)
            print("\n=== DIRECT PARSING MODE (DEFAULT) ===")
            print("Parsing artifacts directly without copying to preserve original file metadata")
            print("Note: Only LNK and Jump List files will be processed. Other files are silently ignored.")
            
            # Get user profiles
            users = get_user_profiles()
            all_unparsed_files = []
            stats = {
                'users_processed': 0,
                'total_recent': 0,
                'total_automatic': 0,
                'total_custom': 0
            }
            
            # Process each user's artifacts directly
            for user in users:
                try:
                    user_artifacts, user_unparsed = parse_user_artifacts_directly(user, db_path)
                    all_unparsed_files.extend(user_unparsed)
                    stats['users_processed'] += 1
                    stats['total_recent'] += len(user_artifacts['recent'])
                    stats['total_automatic'] += len(user_artifacts['automatic'])
                    stats['total_custom'] += len(user_artifacts['custom'])
                except Exception as e:
                    error_msg = f"Error processing user {user}: {e}"
                    print_error_message(error_msg)
                    continue
            
            # Process system artifacts directly
            try:
                system_artifacts, system_unparsed = parse_system_artifacts_directly(db_path)
                all_unparsed_files.extend(system_unparsed)
                stats['total_recent'] += len(system_artifacts['recent'])
                stats['total_automatic'] += len(system_artifacts['automatic'])
                stats['total_custom'] += len(system_artifacts['custom'])
            except Exception as e:
                error_msg = f"Error processing system artifacts: {e}"
                print_error_message(error_msg)
            
            # Print results
            print("\n=== DIRECT PARSING RESULTS ===")
            print(f"LNK Files: {stats['total_recent']}")
            print(f"Automatic Jump Lists: {stats['total_automatic']}")
            print(f"Custom Jump Lists: {stats['total_custom']}")
            print(f"Unparsed files: {len(all_unparsed_files)}")
            if len(all_unparsed_files) > 0:
                print("Note: Unparsed files may be corrupted, unsupported, or inaccessible.")
            
        elif not offline_mode:
            # Normal mode - collect artifacts from the live system then parse
            print("\n=== NORMAL COLLECTION MODE ===")
            print("Collecting artifacts by copying files (use direct_parse=True to avoid copying)")
            print("Note: Only LNK and Jump List files will be processed. Other files are silently ignored.")
            
            collection_stats = collect_forensic_artifacts()
            print("\n=== COLLECTION RESULTS ===")
            # Fix: Use the correct dictionary keys from collect_forensic_artifacts
            # Check if collection_stats is not None before accessing keys
            if collection_stats is not None:
                print(f"LNK Files: {collection_stats['total_recent']}")
                print(f"Automatic Jump Lists: {collection_stats['total_automatic']}")
                print(f"Custom Jump Lists: {collection_stats['total_custom']}")
            else:
                print("Collection failed, no statistics available")
            
            # Then process the collected files into the database
            folder_path = TARGET_BASE_DIR  # Process the entire target directory
            if not os.path.exists(folder_path):
                print(f"Creating folder path: {folder_path}")
                os.makedirs(folder_path, exist_ok=True)
                
            print(f"Processing files from: {folder_path}")
            print("Note: Only LNK and Jump List files will be processed. Other files are silently ignored.")
            
            # Use reusable function to categorize files
            lnk_files, automatic_jump_lists, custom_jump_lists = categorize_files_by_type(folder_path)
            
            # Collect and print processing statistics using reusable function
            file_stats = collect_processing_statistics(lnk_files, automatic_jump_lists, custom_jump_lists)
            print_processing_summary(file_stats, folder_path)
            
            # Process the files
            unparsed_count = process_lnk_and_jump_list_files(folder_path, db_path)
            
            # Update file_stats with unparsed count
            file_stats["unparsed_files"] = unparsed_count
            
            # Print results
            print("\n=== PROCESSING RESULTS ===")
            print(f"Custom Jump Lists: {file_stats['custom_jump_lists']}")
            print(f"Automatic Jump Lists: {file_stats['automatic_jump_lists']}")
            print(f"LNK Files: {file_stats['lnk_files']}")
            print(f"Unparsed files: {file_stats['unparsed_files']}")
            if file_stats['unparsed_files'] > 0:
                print("Note: Unparsed files may be corrupted, unsupported, or inaccessible.")
        else:
            # Offline mode - process artifacts from the case directory
            print("\n=== OFFLINE MODE ===")
            print("Processing artifacts from case directory")
            print("Note: Only LNK and Jump List files will be processed. Other files are silently ignored.")
            # No collection needed, files should already be in the target directories
            
            folder_path = TARGET_BASE_DIR  # Process the entire target directory
            if not os.path.exists(folder_path):
                print(f"Creating folder path: {folder_path}")
                os.makedirs(folder_path, exist_ok=True)
                
            print(f"Processing files from: {folder_path}")
            print("Note: Only LNK and Jump List files will be processed. Other files are silently ignored.")
            
            # Use reusable function to categorize files
            lnk_files, automatic_jump_lists, custom_jump_lists = categorize_files_by_type(folder_path)
            
            # Collect and print processing statistics using reusable function
            file_stats = collect_processing_statistics(lnk_files, automatic_jump_lists, custom_jump_lists)
            print_processing_summary(file_stats, folder_path)
            
            # Process the files
            unparsed_count = process_lnk_and_jump_list_files(folder_path, db_path)
            
            # Update file_stats with unparsed count
            file_stats["unparsed_files"] = unparsed_count
            
            # Print results
            print("\n=== PROCESSING RESULTS ===")
            print(f"Custom Jump Lists: {file_stats['custom_jump_lists']}")
            print(f"Automatic Jump Lists: {file_stats['automatic_jump_lists']}")
            print(f"LNK Files: {file_stats['lnk_files']}")
            print(f"Unparsed files: {file_stats['unparsed_files']}")
            if file_stats['unparsed_files'] > 0:
                print("Note: Unparsed files may be corrupted, unsupported, or inaccessible.")
        
    except KeyboardInterrupt:
        print("\nCollection aborted by user.")
        return None
    except Exception as e:
        error_msg = f"\n [!!!] Critical error: {str(e)}"
        print_error_message(error_msg)
        import traceback
        traceback.print_exc()
        return None

    print(f"\033[92m\nParsing automatic,custom jumplist and LNK files has been completed by Crow Eye\nDatabase saved to: {db_path}\033[0m")
    return db_path

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Collect and process LNK and Jump List artifacts")
    parser.add_argument("--case", "-c", help="Path to case directory")
    parser.add_argument("--offline", "-o", action="store_true", help="Run in offline mode")
    parser.add_argument("--direct", "-d", action="store_true", default=True, help="Parse artifacts directly without copying (default behavior)")
    parser.add_argument("--copy", action="store_true", help="Copy files before parsing (opposite of direct parsing)")
    args = parser.parse_args()
    
    # If --copy is specified, disable direct parsing
    direct_parse = not args.copy
    
    A_CJL_LNK_Claw(args.case, args.offline, direct_parse)
