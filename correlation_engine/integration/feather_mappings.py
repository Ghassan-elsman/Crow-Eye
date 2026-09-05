"""
Feather Mappings Configuration

Defines all 41 Feather generation mappings from Crow-Eye parser output.
Each carries `fallback_columns`, read from the parser's own CREATE TABLE, so a
case parsed before a table existed still yields an empty feather rather than
failing the mapping and taking every wing that references it down with it.
Each mapping specifies source database, table, artifact type, and column exclusions.
Enhanced with improved artifact type detection and subtype categorization.
"""

from typing import List, Dict, Optional


# Enhanced artifact type mappings with subtypes
ENHANCED_ARTIFACT_TYPES = {
    'StartupApproved': {
        'parent_type': 'Registry',
        'description': 'Whether each autostart entry is allowed to launch',
        'forensic_value': 'High - corrects AutoStartPrograms false positives'
    },
    'AppPaths': {
        'parent_type': 'Registry',
        'description': 'How a bare command name resolves to an executable',
        'forensic_value': 'High - a hijack point with no path to give it away'
    },
    'SafeBootServices': {
        'parent_type': 'Registry',
        'description': 'What still starts in Safe Mode',
        'forensic_value': 'High - persistence that survives a clean boot'
    },
    'ScheduledTasks': {
        'parent_type': 'Registry',
        'description': 'Task Scheduler entries from the registry TaskCache',
        'forensic_value': 'High - a top-tier persistence mechanism'
    },
    'ActiveSetup': {
        'parent_type': 'Registry',
        'description': 'Per-user commands run once at first logon',
        'forensic_value': 'High - a well-worn persistence location'
    },
    'SharedDLLs': {
        'parent_type': 'Registry',
        'description': 'Reference counts for shared libraries',
        'forensic_value': 'Low - inventory, occasionally the only install record'
    },
    'HIDDevices': {
        'parent_type': 'Registry',
        'description': 'Human interface devices the machine enumerated',
        'forensic_value': 'Medium - catches a device presenting as a keyboard'
    },
    'NetworkCards': {
        'parent_type': 'Registry',
        'description': 'The adapter inventory by installation index',
        'forensic_value': 'Medium - names cards with no surviving interface'
    },
    'ZoneMap': {
        'parent_type': 'Registry',
        'description': 'Hosts and protocols assigned to a security zone',
        'forensic_value': 'High - a host in Trusted Sites runs blocked content'
    },
    'AppPermissions': {
        'parent_type': 'Registry',
        'description': 'Microphone, camera and location consent, and last use',
        'forensic_value': "High - the registry's own record of capture access"
    },
    'SystemConfiguration': {
        'parent_type': 'Registry',
        'description': 'Power, locale, time source, TCP/IP identity, shell folders',
        'forensic_value': 'Medium - HiberbootEnabled decides if a shutdown was one'
    },
    'SecurityPosture': {
        'parent_type': 'Registry',
        'description': 'Security settings against their stock defaults',
        'forensic_value': 'High - what was turned off, and when'
    },
    'FirewallRules': {
        'parent_type': 'Registry',
        'description': 'Firewall rules including direction, port and application',
        'forensic_value': 'High - an added inbound rule is an exposure'
    },
    'WinevtChannels': {
        'parent_type': 'Registry',
        'description': 'Which event log channels were enabled, and how big',
        'forensic_value': 'High - a disabled channel explains a silence'
    },
    # Registry subtypes - more specific categorization
    'UserAssist': {
        'parent_type': 'Registry',
        'description': 'User application execution tracking',
        'forensic_value': 'High - Direct execution evidence'
    },
    'ShellBags': {
        'parent_type': 'Registry', 
        'description': 'Folder access and navigation history',
        'forensic_value': 'Medium - User activity evidence'
    },
    'MUICache': {
        'parent_type': 'Registry',
        'description': 'Application execution cache',
        'forensic_value': 'High - Execution evidence'
    },
    'RecentDocs': {
        'parent_type': 'Registry',
        'description': 'Recently accessed documents',
        'forensic_value': 'Medium - Document access evidence'
    },
    'OpenSaveMRU': {
        'parent_type': 'Registry',
        'description': 'File open/save dialog history',
        'forensic_value': 'Medium - File interaction evidence'
    },
    'LastSaveMRU': {
        'parent_type': 'Registry',
        'description': 'Last save location history',
        'forensic_value': 'Medium - File save evidence'
    },
    'TypedPaths': {
        'parent_type': 'Registry',
        'description': 'Manually typed file paths',
        'forensic_value': 'Medium - User navigation evidence'
    },
    'WordWheelQuery': {
        'parent_type': 'Registry',
        'description': 'Windows search queries',
        'forensic_value': 'Medium - Search behavior evidence'
    },
    'BAM': {
        'parent_type': 'Registry',
        'description': 'Background Activity Moderator',
        'forensic_value': 'High - Application execution evidence'
    },
    'InstalledSoftware': {
        'parent_type': 'Registry',
        'description': 'Software installation records',
        'forensic_value': 'Medium - System configuration evidence'
    },
    'SystemServices': {
        'parent_type': 'Registry',
        'description': 'Windows system services',
        'forensic_value': 'Medium - System configuration evidence'
    },
    'AutoStartPrograms': {
        'parent_type': 'Registry',
        'description': 'Programs configured to start automatically',
        'forensic_value': 'High - Persistence mechanism evidence'
    },
    
    # SRUM subtypes
    'SRUM_ApplicationUsage': {
        'parent_type': 'SRUM',
        'description': 'Application resource usage statistics',
        'forensic_value': 'Medium - Application behavior evidence'
    },
    'SRUM_NetworkDataUsage': {
        'parent_type': 'SRUM',
        'description': 'Network data usage by application',
        'forensic_value': 'Medium - Network activity evidence'
    },
    
    # Log subtypes
    'SecurityLogs': {
        'parent_type': 'Logs',
        'description': 'Windows Security event logs',
        'forensic_value': 'High - Security event evidence'
    },
    'SystemLogs': {
        'parent_type': 'Logs',
        'description': 'Windows System event logs',
        'forensic_value': 'Medium - System event evidence'
    },
    'ApplicationLogs': {
        'parent_type': 'Logs',
        'description': 'Windows Application event logs',
        'forensic_value': 'Medium - Application event evidence'
    },
    
    # AmCache subtypes
    'InventoryApplication': {
        'parent_type': 'AmCache',
        'description': 'Application inventory from AmCache',
        'forensic_value': 'High - Application execution evidence'
    },
    'InventoryApplicationFile': {
        'parent_type': 'AmCache',
        'description': 'Application file inventory from AmCache',
        'forensic_value': 'High - File execution evidence'
    },
    'InventoryApplicationShortcut': {
        'parent_type': 'AmCache',
        'description': 'Application shortcut inventory from AmCache',
        'forensic_value': 'Medium - Shortcut usage evidence'
    },
    
    # Jumplist subtypes
    'AutomaticJumplist': {
        'parent_type': 'Jumplists',
        'description': 'Automatic Windows Jump Lists',
        'forensic_value': 'Medium - Recent file access evidence'
    },
    'CustomJumplist': {
        'parent_type': 'Jumplists',
        'description': 'Custom Windows Jump Lists',
        'forensic_value': 'Medium - Application-specific evidence'
    }
}


def detect_artifact_type_from_name(feather_name: str, table_name: str = None, db_name: str = None) -> str:
    """
    Enhanced artifact type detection from feather name, table, or database.
    
    Args:
        feather_name: Name of the feather
        table_name: Optional source table name
        db_name: Optional source database name
        
    Returns:
        Detected artifact type (specific subtype if available, otherwise parent type)
    """
    # Remove common suffixes
    clean_name = feather_name.replace('_CrowEyeFeather', '').replace('CrowEyeFeather', '')
    
    # Check for exact matches in enhanced types
    if clean_name in ENHANCED_ARTIFACT_TYPES:
        return clean_name
    
    # Check for partial matches
    for artifact_type in ENHANCED_ARTIFACT_TYPES:
        if artifact_type.lower() in clean_name.lower():
            return artifact_type
    
    # Fallback to table name detection
    if table_name:
        for artifact_type in ENHANCED_ARTIFACT_TYPES:
            if artifact_type.lower() in table_name.lower():
                return artifact_type
    
    # Fallback to database name detection
    if db_name:
        db_mappings = {
            'registry': 'Registry',
            'amcache': 'AmCache', 
            'prefetch': 'Prefetch',
            'shimcache': 'ShimCache',
            'srum': 'SRUM',
            'log': 'Logs',
            'mft': 'MFT',
            'lnk': 'LNK',
            'jumplist': 'Jumplists',
            'recycle': 'RecycleBin'
        }
        
        db_lower = db_name.lower()
        for key, artifact_type in db_mappings.items():
            if key in db_lower:
                return artifact_type
    
    # Final fallback - return the clean name or "Unknown"
    return clean_name if clean_name else "Unknown"


def get_parent_artifact_type(artifact_type: str) -> str:
    """
    Get the parent artifact type for a subtype.
    
    Args:
        artifact_type: Specific artifact type
        
    Returns:
        Parent artifact type or the same type if it's already a parent
    """
    if artifact_type in ENHANCED_ARTIFACT_TYPES:
        return ENHANCED_ARTIFACT_TYPES[artifact_type]['parent_type']
    return artifact_type


def get_artifact_type_info(artifact_type: str) -> Dict:
    """
    Get detailed information about an artifact type.
    
    Args:
        artifact_type: Artifact type name
        
    Returns:
        Dictionary with type information
    """
    if artifact_type in ENHANCED_ARTIFACT_TYPES:
        return ENHANCED_ARTIFACT_TYPES[artifact_type]
    
    # Return basic info for unknown types
    return {
        'parent_type': artifact_type,
        'description': f'{artifact_type} forensic artifact',
        'forensic_value': 'Unknown'
    }


# Complete list of all 27 Feather generation mappings with enhanced artifact types
FEATHER_MAPPINGS: List[Dict] = [
    # ========== AmCache (3 Feathers) ==========
    {
        'name': 'InventoryApplication_CrowEyeFeather',
        'source_db': 'amcache.db',
        'source_table': 'InventoryApplication',
        'artifact_type': 'InventoryApplication', # Enhanced: specific subtype
        'parent_type': 'AmCache',
        'fallback_columns': [
        ('program_id', 'TEXT'), ('name', 'TEXT'), ('version', 'TEXT'),
        ('publisher', 'TEXT'), ('language', 'TEXT'), ('source', 'TEXT'),
        ('root_dir_path', 'TEXT'), ('default_value', 'TEXT'),
        ('program_instance_id', 'TEXT'), ('store_app_type', 'TEXT'),
        ('inbox_modern_app', 'TEXT'), ('manifest_path', 'TEXT'),
        ('package_full_name', 'TEXT'), ('install_date', 'TEXT'),
        ('hidden_arp', 'TEXT'), ('uninstall_string', 'TEXT'),
        ('registry_key_path', 'TEXT'), ('msi_package_code', 'TEXT'),
        ('msi_product_code', 'TEXT'), ('msi_install_date', 'TEXT'),
        ('bundle_manifest_path', 'TEXT'), ('user_sid', 'TEXT'),
        ('install_date_utc', 'TEXT'), ('msi_install_date_utc', 'TEXT'),
        ('key_last_write', 'TEXT'), ('parsed_at', 'TEXT')
        ]
    },
    {
        'name': 'InventoryApplicationFile_CrowEyeFeather',
        'source_db': 'amcache.db',
        'source_table': 'InventoryApplicationFile',
        'artifact_type': 'InventoryApplicationFile', # Enhanced: specific subtype
        'parent_type': 'AmCache',
        'fallback_columns': [
        ('program_id', 'TEXT'), ('file_id', 'TEXT'),
        ('lower_case_long_path', 'TEXT'), ('name', 'TEXT'),
        ('binary_type', 'TEXT'), ('link_date', 'TEXT'), ('size', 'INTEGER'),
        ('language', 'TEXT'), ('usn', 'INTEGER'),
        ('bin_file_version', 'TEXT'), ('bin_product_version', 'TEXT'),
        ('product_version', 'TEXT'), ('version', 'TEXT'),
        ('product_name', 'TEXT'), ('publisher', 'TEXT'),
        ('original_file_name', 'TEXT'), ('appx_package_full_name', 'TEXT'),
        ('is_os_component', 'TEXT'), ('appx_package_relative_id', 'TEXT'),
        ('link_date_utc', 'TEXT'), ('file_id_is_partial', 'TEXT'),
        ('file_id_verified', 'TEXT'), ('program_association', 'TEXT'),
        ('key_last_write', 'TEXT'), ('parsed_at', 'TEXT')
        ]
    },
    {
        'name': 'InventoryApplicationShortcut_CrowEyeFeather',
        'source_db': 'amcache.db',
        'source_table': 'InventoryApplicationShortcut',
        'artifact_type': 'InventoryApplicationShortcut', # Enhanced: specific subtype
        'parent_type': 'AmCache',
        'fallback_columns': [
        ('shortcut_path', 'TEXT'), ('shortcut_target_path', 'TEXT'),
        ('shortcut_aumid', 'TEXT'), ('shortcut_program_id', 'TEXT'),
        ('default_value', 'TEXT'), ('key_last_write', 'TEXT'),
        ('parsed_at', 'TEXT')
        ]
    },
    
    # ========== LNK and Jumplists (3 Feathers) ==========
    {
        'name': 'LNK_CrowEyeFeather',
        'source_db': 'LnkDB.db',
        'source_table': 'LNK_Files',
        'artifact_type': 'LNK',
        'parent_type': 'LNK',
        'fallback_columns': [
        ('Source_Name', 'TEXT'), ('Source_Path', 'TEXT'), ('Owner_UID', 'INTEGER'),
        ('Owner_GID', 'INTEGER'), ('File_Permission', 'TEXT'),
        ('Num_Hard_Links', 'INTEGER'), ('Device_ID', 'INTEGER'),
        ('Inode_Number', 'INTEGER'), ('Time_Access', 'TEXT'), ('Time_Creation', 'TEXT'),
        ('Time_Modification', 'TEXT'), ('LNK_Class_ID', 'TEXT'), ('Link_Flags', 'TEXT'),
        ('File_Attributes_Flags', 'TEXT'), ('FileSize', 'TEXT'), ('IconIndex', 'INTEGER'),
        ('Show_Window_Command', 'TEXT'), ('Hot_Key_Flags', 'TEXT'),
        ('Hot_Key_Value', 'TEXT'), ('Local_Path', 'TEXT'), ('Target_Source', 'TEXT'),
        ('Network_Share_Name', 'TEXT'), ('Common_Path', 'TEXT'), ('Relative_Path', 'TEXT'),
        ('Working_Directory', 'TEXT'), ('Command_Line_Arguments', 'TEXT'),
        ('Icon_Location', 'TEXT'), ('Description', 'TEXT'), ('Volume_Type', 'TEXT'),
        ('Volume_Serial', 'TEXT'), ('Volume_Label', 'TEXT'), ('MFT_Entry_Number', 'TEXT'),
        ('MFT_Sequence_Number', 'TEXT'), ('Tracker_NetBIOS', 'TEXT'),
        ('Tracker_MAC', 'TEXT'), ('Property_Metadata', 'TEXT'), ('Darwin_ID', 'TEXT'),
        ('Environment_Variables', 'TEXT'), ('Known_Folder_GUID', 'TEXT')
        ],
        'filter': None, # No filter needed - dedicated table
        'column_mapping': {'Local_Path': 'target_path'} # Standardize for correlation
    },
    {
        'name': 'AutomaticJumplist_CrowEyeFeather',
        'source_db': 'LnkDB.db',
        'source_table': 'Automatic_JumpLists',
        'artifact_type': 'AutomaticJumplist', # Enhanced: specific subtype
        'parent_type': 'Jumplists',
        'fallback_columns': [
        ('Source_Name', 'TEXT'), ('Source_Path', 'TEXT'), ('entry_number', 'TEXT'),
        ('Owner_UID', 'INTEGER'), ('Owner_GID', 'INTEGER'), ('File_Permission', 'TEXT'),
        ('Num_Hard_Links', 'INTEGER'), ('Device_ID', 'INTEGER'),
        ('Inode_Number', 'INTEGER'), ('AppID', 'TEXT'), ('AppType', 'TEXT'),
        ('AppDesc', 'TEXT'), ('Time_Access', 'TEXT'), ('Time_Creation', 'TEXT'),
        ('Time_Modification', 'TEXT'), ('LNK_Class_ID', 'TEXT'), ('Link_Flags', 'TEXT'),
        ('File_Attributes_Flags', 'TEXT'), ('FileSize', 'TEXT'), ('IconIndex', 'INTEGER'),
        ('Show_Window_Command', 'TEXT'), ('Hot_Key_Flags', 'TEXT'),
        ('Hot_Key_Value', 'TEXT'), ('Local_Path', 'TEXT'), ('Target_Source', 'TEXT'),
        ('Network_Share_Name', 'TEXT'), ('Common_Path', 'TEXT'), ('Relative_Path', 'TEXT'),
        ('Working_Directory', 'TEXT'), ('Command_Line_Arguments', 'TEXT'),
        ('Icon_Location', 'TEXT'), ('Description', 'TEXT'), ('Volume_Type', 'TEXT'),
        ('Volume_Serial', 'TEXT'), ('Volume_Label', 'TEXT'), ('MFT_Entry_Number', 'TEXT'),
        ('MFT_Sequence_Number', 'TEXT'), ('Tracker_NetBIOS', 'TEXT'),
        ('Tracker_MAC', 'TEXT'), ('DestList_Version_Number', 'INTEGER'),
        ('DestList_OS_Version', 'TEXT'), ('DestList_Total_Current_Entries', 'INTEGER'),
        ('DestList_Total_Pinned_Entries', 'INTEGER'), ('DestList_Last_ID', 'INTEGER'),
        ('DestList_Actions_Count', 'INTEGER'), ('DestList_Checksum', 'TEXT'),
        ('DestList_New_Volume_ID', 'TEXT'), ('DestList_New_Object_ID', 'TEXT'),
        ('Birth_Volume_ID', 'TEXT'), ('Birth_Object_ID', 'TEXT'),
        ('Birth_Object_ID_MAC', 'TEXT'), ('DestList_Access_Counter', 'INTEGER'),
        ('DestList_Pin_Status', 'TEXT'), ('Embedded_LNK', 'TEXT'),
        ('Property_Metadata', 'TEXT'), ('Darwin_ID', 'TEXT'),
        ('Environment_Variables', 'TEXT'), ('Known_Folder_GUID', 'TEXT')
        ],
        'filter': None, # No filter needed - dedicated table
        'column_mapping': {'Local_Path': 'path'} # Standardize for correlation
    },
    {
        'name': 'CustomJumplist_CrowEyeFeather',
        'source_db': 'LnkDB.db',
        'source_table': 'Custom_JumpLists',
        'artifact_type': 'CustomJumplist', # Enhanced: specific subtype
        'parent_type': 'Jumplists',
        'fallback_columns': [
        ('entry_id', 'INTEGER'), ('Source_Name', 'TEXT'), ('Source_Path', 'TEXT'),
        ('Owner_UID', 'INTEGER'), ('Owner_GID', 'INTEGER'), ('File_Permission', 'TEXT'),
        ('Num_Hard_Links', 'INTEGER'), ('Device_ID', 'INTEGER'),
        ('Inode_Number', 'INTEGER'), ('AppID', 'TEXT'), ('AppType', 'TEXT'),
        ('AppDesc', 'TEXT'), ('Category', 'TEXT'), ('Footer_Signature_Valid', 'INTEGER'),
        ('Time_Access', 'TEXT'), ('Time_Creation', 'TEXT'), ('Time_Modification', 'TEXT'),
        ('LNK_Class_ID', 'TEXT'), ('Link_Flags', 'TEXT'),
        ('File_Attributes_Flags', 'TEXT'), ('FileSize', 'TEXT'), ('IconIndex', 'INTEGER'),
        ('Show_Window_Command', 'TEXT'), ('Hot_Key_Flags', 'TEXT'),
        ('Hot_Key_Value', 'TEXT'), ('Local_Path', 'TEXT'), ('Target_Source', 'TEXT'),
        ('Network_Share_Name', 'TEXT'), ('Common_Path', 'TEXT'), ('Relative_Path', 'TEXT'),
        ('Working_Directory', 'TEXT'), ('Command_Line_Arguments', 'TEXT'),
        ('Icon_Location', 'TEXT'), ('Description', 'TEXT'), ('Volume_Type', 'TEXT'),
        ('Volume_Serial', 'TEXT'), ('Volume_Label', 'TEXT'), ('MFT_Entry_Number', 'TEXT'),
        ('MFT_Sequence_Number', 'TEXT'), ('Tracker_NetBIOS', 'TEXT'),
        ('Tracker_MAC', 'TEXT'), ('Embedded_LNK', 'TEXT'), ('Property_Metadata', 'TEXT'),
        ('Darwin_ID', 'TEXT'), ('Environment_Variables', 'TEXT'),
        ('Known_Folder_GUID', 'TEXT')
        ],
        'filter': None, # No filter needed - dedicated table
        'column_mapping': {'Local_Path': 'path'} # Standardize for correlation
    },
    
    # ========== Event Logs (3 Feathers) ==========
    {
        'name': 'SecurityLogs_CrowEyeFeather',
        'source_db': 'Log_Claw.db',
        'source_table': 'SecurityLogs',
        'artifact_type': 'SecurityLogs', # Enhanced: specific subtype
        'parent_type': 'Logs',
        'fallback_columns': [
        ('EventID', 'INTEGER'), ('Source', 'TEXT'), ('EventType', 'TEXT'),
        ('Category', 'TEXT'), ('EventTimestampUTC', 'TEXT'), ('ComputerName', 'TEXT'),
        ('User', 'TEXT'), ('Keywords', 'TEXT'), ('TaskCategory', 'TEXT'),
        ('EventDescription', 'TEXT')
        ]
    },
    {
        'name': 'SystemLogs_CrowEyeFeather',
        'source_db': 'Log_Claw.db',
        'source_table': 'SystemLogs',
        'artifact_type': 'SystemLogs', # Enhanced: specific subtype
        'parent_type': 'Logs',
        'fallback_columns': [
        ('EventID', 'INTEGER'), ('Source', 'TEXT'), ('EventType', 'TEXT'),
        ('Category', 'TEXT'), ('EventTimestampUTC', 'TEXT'), ('ComputerName', 'TEXT'),
        ('User', 'TEXT'), ('Keywords', 'TEXT'), ('EventDescription', 'TEXT')
        ]
    },
    {
        'name': 'ApplicationLogs_CrowEyeFeather',
        'source_db': 'Log_Claw.db',
        'source_table': 'ApplicationLogs',
        'artifact_type': 'ApplicationLogs', # Enhanced: specific subtype
        'parent_type': 'Logs',
        'fallback_columns': [
        ('EventID', 'INTEGER'), ('Source', 'TEXT'), ('EventType', 'TEXT'),
        ('Category', 'TEXT'), ('EventTimestampUTC', 'TEXT'), ('ComputerName', 'TEXT'),
        ('User', 'TEXT'), ('Keywords', 'TEXT'), ('EventDescription', 'TEXT')
        ]
    },
    
    # ========== MFT/USN (1 Feather) ==========
    {
        'name': 'MFT_USN_Correlated_CrowEyeFeather',
        'source_db': 'mft_usn_correlated_analysis.db',
        'source_table': 'mft_usn_correlated',
        # Legacy bookkeeping alias for this table; see
        # BOOKKEEPING_COLUMNS in auto_feather_generator.py for why
        # this is per-table and not a global name.
        'bookkeeping_columns': ['created_at'],
        'artifact_type': 'MFT',
        'parent_type': 'MFT',
        'fallback_columns': [
        ('volume_letter', 'TEXT'), ('mft_record_number', 'INTEGER'),
        ('fn_filename', 'TEXT'), ('mft_sequence_number', 'INTEGER'), ('mft_flags', 'TEXT'),
        ('is_directory', 'INTEGER'), ('is_deleted', 'INTEGER'), ('file_extension', 'TEXT'),
        ('file_size', 'INTEGER'), ('in_use', 'INTEGER'), ('has_ads', 'INTEGER'),
        ('ads_count', 'INTEGER'), ('si_creation_time', 'TEXT'),
        ('si_modification_time', 'TEXT'), ('si_access_time', 'TEXT'),
        ('si_mft_entry_change_time', 'TEXT'), ('si_file_attributes', 'TEXT'),
        ('fn_parent_record_number', 'INTEGER'), ('fn_parent_sequence_number', 'INTEGER'),
        ('fn_namespace', 'TEXT'), ('fn_creation_time', 'TEXT'),
        ('fn_modification_time', 'TEXT'), ('fn_access_time', 'TEXT'),
        ('fn_mft_entry_change_time', 'TEXT'), ('fn_allocated_size', 'INTEGER'),
        ('fn_real_size', 'INTEGER'), ('fn_file_attributes', 'TEXT'),
        ('reconstructed_path', 'TEXT'), ('usn_event_id', 'INTEGER'),
        ('usn_timestamp', 'TEXT'), ('usn_reason', 'TEXT'), ('usn_source_info', 'TEXT'),
        ('usn_file_attributes', 'TEXT'), ('usn_filename', 'TEXT'), ('usn_frn', 'TEXT'),
        ('usn_parent_frn', 'TEXT'), ('usn_security_id', 'INTEGER'),
        ('has_mft_record', 'INTEGER'), ('has_usn_event', 'INTEGER'),
        ('correlation_confidence', 'TEXT'), ('filename_change_timeline', 'TEXT'),
        ('namespace_evolution', 'TEXT'), ('created_at', 'TEXT')
        ]
    },
    
    # ========== Prefetch (1 Feather) ==========
    {
        'name': 'Prefetch_CrowEyeFeather',
        'source_db': 'prefetch_data.db',
        'source_table': 'prefetch_data',
        'artifact_type': 'Prefetch',
        'parent_type': 'Prefetch',
        'fallback_columns': [
        ('filename', 'TEXT'), ('executable_name', 'TEXT'), ('hash', 'TEXT'),
        ('run_count', 'INTEGER'), ('last_executed', 'TEXT'), ('run_times', 'TEXT'),
        ('volumes', 'TEXT'), ('directories', 'TEXT'), ('resources', 'TEXT'),
        ('created_on', 'TEXT'), ('modified_on', 'TEXT'), ('accessed_on', 'TEXT')
        ]
    },
    
    # ========== RecycleBin (1 Feather) ==========
    {
        'name': 'RecycleBin_CrowEyeFeather',
        'source_db': 'recyclebin_analysis.db',
        'source_table': 'recycle_bin_entries',
        'artifact_type': 'RecycleBin',
        'parent_type': 'RecycleBin',
        'fallback_columns': [
        ('original_filename', 'TEXT'), ('original_path', 'TEXT'),
        ('deletion_time', 'TEXT'), ('formatted_file_size', 'TEXT'), ('user_sid', 'TEXT'),
        ('recycle_bin_path', 'TEXT'), ('r_file_path', 'TEXT'),
        ('random_i_filename', 'TEXT'), ('random_r_filename', 'TEXT'),
        ('file_signature', 'TEXT'), ('recovery_status', 'TEXT'), ('parsed_at', 'TEXT')
        ]
    },
    
    # ========== Registry (12 Feathers) - Enhanced with specific subtypes ==========
    {
        'name': 'BAM_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'BAM',
        # Legacy bookkeeping alias for this table; see
        # BOOKKEEPING_COLUMNS in auto_feather_generator.py for why
        # this is per-table and not a global name.
        'bookkeeping_columns': ['timestamp'],
        'artifact_type': 'BAM', # Enhanced: specific subtype
        'parent_type': 'Registry',
        'fallback_columns': [
        ('subkey', 'TEXT'), ('name', 'TEXT'), ('row_data', 'TEXT'), ('type', 'TEXT'),
        ('app_name', 'TEXT'), ('process_path', 'TEXT'), ('sid', 'TEXT'),
        ('last_execution', 'TEXT'), ('decoded', 'TEXT'),
        ('name_kind', 'TEXT'), ('name_kind_raw', 'INTEGER'),
        ('trailing_value', 'INTEGER'),
        ('last_written', 'TEXT'), ('time_basis', 'TEXT'), ('parsed_at', 'TEXT')
        ]
    },
    {
        'name': 'InstalledSoftware_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'InstalledSoftware',
        # Legacy bookkeeping alias for this table; see
        # BOOKKEEPING_COLUMNS in auto_feather_generator.py for why
        # this is per-table and not a global name.
        'bookkeeping_columns': ['timestamp'],
        'artifact_type': 'InstalledSoftware', # Enhanced: specific subtype
        'parent_type': 'Registry',
        'fallback_columns': [
        ('display_name', 'TEXT'), ('display_version', 'TEXT'), ('publisher', 'TEXT'),
        ('install_date', 'TEXT'), ('install_location', 'TEXT'),
        ('uninstall_string', 'TEXT'), ('parsed_at', 'TEXT')
        ]
    },
    {
        'name': 'LastSaveMRU_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'LastSaveMRU',
        # Legacy bookkeeping alias for this table; see
        # BOOKKEEPING_COLUMNS in auto_feather_generator.py for why
        # this is per-table and not a global name.
        'bookkeeping_columns': ['analyzing_date'],
        'artifact_type': 'LastSaveMRU', # Enhanced: specific subtype
        'parent_type': 'Registry',
        'fallback_columns': [
        ('mru_number', 'TEXT'), ('type', 'TEXT'), ('application', 'TEXT'),
        ('folder_path', 'TEXT'), ('folder_name', 'TEXT'), ('drive_letter', 'TEXT'),
        ('access_date', 'TEXT'), ('key_last_write', 'TEXT'), ('row_data', 'TEXT'),
        ('parsed_at', 'TEXT'), ('user_name', 'TEXT')
        ]
    },
    {
        'name': 'MUICache_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'MUICache',
        # Legacy bookkeeping alias for this table; see
        # BOOKKEEPING_COLUMNS in auto_feather_generator.py for why
        # this is per-table and not a global name.
        'bookkeeping_columns': ['timestamp'],
        'artifact_type': 'MUICache', # Enhanced: specific subtype
        'parent_type': 'Registry',
        'fallback_columns': [
        ('app_path', 'TEXT'), ('app_name', 'TEXT'), ('company', 'TEXT'),
        ('file_extension', 'TEXT'), ('parsed_at', 'TEXT'), ('user_name', 'TEXT')
        ]
    },
    {
        'name': 'OpenSaveMRU_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'OpenSaveMRU',
        # Legacy bookkeeping alias for this table; see
        # BOOKKEEPING_COLUMNS in auto_feather_generator.py for why
        # this is per-table and not a global name.
        'bookkeeping_columns': ['analyzing_date'],
        'artifact_type': 'OpenSaveMRU', # Enhanced: specific subtype
        'parent_type': 'Registry',
        'fallback_columns': [
        ('subkey', 'TEXT'), ('name', 'TEXT'), ('type', 'TEXT'), ('file_path', 'TEXT'),
        ('file_name', 'TEXT'), ('extension', 'TEXT'), ('drive_letter', 'TEXT'),
        ('access_date', 'TEXT'), ('key_last_write', 'TEXT'), ('row_data', 'TEXT'),
        ('parsed_at', 'TEXT'), ('user_name', 'TEXT')
        ]
    },
    {
        'name': 'RecentDocs_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'RecentDocs',
        # Legacy bookkeeping alias for this table; see
        # BOOKKEEPING_COLUMNS in auto_feather_generator.py for why
        # this is per-table and not a global name.
        'bookkeeping_columns': ['timestamp'],
        'artifact_type': 'RecentDocs', # Enhanced: specific subtype
        'parent_type': 'Registry',
        'fallback_columns': [
        ('subkey', 'TEXT'), ('name', 'TEXT'), ('row_data', 'TEXT'), ('type', 'TEXT'),
        ('user_name', 'TEXT'), ('mru_position', 'INTEGER'), ('key_last_write', 'TEXT'),
        ('parsed_at', 'TEXT')
        ]
    },
    {
        'name': 'ShellBags_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'Shellbags',
        # Legacy bookkeeping alias for this table; see
        # BOOKKEEPING_COLUMNS in auto_feather_generator.py for why
        # this is per-table and not a global name.
        'bookkeeping_columns': ['analyzing_date'],
        'artifact_type': 'ShellBags', # Enhanced: specific subtype
        'parent_type': 'Registry',
        'fallback_columns': [
        ('file_name', 'TEXT'), ('short_name', 'TEXT'), ('shell_item_type', 'TEXT'),
        ('mru_position', 'TEXT'), ('created_date', 'TEXT'), ('modified_date', 'TEXT'),
        ('accessed_date', 'TEXT'), ('attributes', 'TEXT'), ('file_size', 'INTEGER'),
        ('special_folder', 'TEXT'), ('network_share', 'TEXT'), ('server_name', 'TEXT'),
        ('share_name', 'TEXT'), ('drive_letter', 'TEXT'), ('mft_record_number', 'INTEGER'),
        ('registry_path', 'TEXT'), ('parent_path', 'TEXT'), ('last_written', 'TEXT'),
        ('time_basis', 'TEXT'), ('node_slot', 'INTEGER'), ('bag_views', 'TEXT'),
        ('parsed_at', 'TEXT'), ('user_name', 'TEXT')
        ]
    },
    {
        'name': 'SystemServices_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'SystemServices',
        # Legacy bookkeeping alias for this table; see
        # BOOKKEEPING_COLUMNS in auto_feather_generator.py for why
        # this is per-table and not a global name.
        'bookkeeping_columns': ['timestamp'],
        'artifact_type': 'SystemServices', # Enhanced: specific subtype
        'parent_type': 'Registry',
        'fallback_columns': [
        ('service_name', 'TEXT'), ('display_name', 'TEXT'), ('description', 'TEXT'),
        ('image_path', 'TEXT'), ('start_type', 'INTEGER'), ('service_type', 'INTEGER'),
        ('error_control', 'INTEGER'), ('status', 'TEXT'), ('parsed_at', 'TEXT')
        ]
    },
    {
        'name': 'TypedPaths_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'TypedPaths',
        # Legacy bookkeeping alias for this table; see
        # BOOKKEEPING_COLUMNS in auto_feather_generator.py for why
        # this is per-table and not a global name.
        'bookkeeping_columns': ['timestamp'],
        'artifact_type': 'TypedPaths', # Enhanced: specific subtype
        'parent_type': 'Registry',
        'fallback_columns': [
        ('name', 'TEXT'), ('row_data', 'TEXT'), ('type', 'TEXT'), ('user_name', 'TEXT'),
        ('mru_position', 'INTEGER'), ('key_last_write', 'TEXT'), ('parsed_at', 'TEXT')
        ]
    },
    {
        'name': 'WordWheelQuery_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'WordWheelQuery',
        # Legacy bookkeeping alias for this table; see
        # BOOKKEEPING_COLUMNS in auto_feather_generator.py for why
        # this is per-table and not a global name.
        'bookkeeping_columns': ['timestamp'],
        'artifact_type': 'WordWheelQuery', # Enhanced: specific subtype
        'parent_type': 'Registry',
        'fallback_columns': [
        ('search_term', 'TEXT'), ('search_type', 'TEXT'), ('mru_position', 'INTEGER'),
        ('access_date', 'TEXT'), ('key_last_write', 'TEXT'), ('parsed_at', 'TEXT'),
        ('user_name', 'TEXT')
        ]
    },
    {
        'name': 'UserAssist_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'UserAssist',
        # Legacy bookkeeping alias for this table; see
        # BOOKKEEPING_COLUMNS in auto_feather_generator.py for why
        # this is per-table and not a global name.
        'bookkeeping_columns': ['timestamp'],
        'artifact_type': 'UserAssist', # Enhanced: specific subtype instead of generic "Registry"
        'parent_type': 'Registry',
        'fallback_columns': [
        ('program_path', 'TEXT'), ('run_count', 'INTEGER'), ('last_execution', 'TEXT'),
        ('focus_count', 'INTEGER'), ('focus_time', 'INTEGER'), ('user_sid', 'TEXT'),
        ('parsed_at', 'TEXT')
        ]
    },
    {
        'name': 'AutoStartPrograms_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'AutoStartPrograms',
        # Legacy bookkeeping alias for this table; see
        # BOOKKEEPING_COLUMNS in auto_feather_generator.py for why
        # this is per-table and not a global name.
        'bookkeeping_columns': ['timestamp'],
        'artifact_type': 'AutoStartPrograms', # Enhanced: specific subtype
        'parent_type': 'Registry',
        'fallback_columns': [
        ('location', 'TEXT'), ('program_name', 'TEXT'), ('command', 'TEXT'),
        ('key_path', 'TEXT'), ('startup_state', 'TEXT'), ('disabled_at', 'TEXT'),
        ('record_state', 'TEXT'), ('last_written', 'TEXT'), ('time_basis', 'TEXT'),
        ('parsed_at', 'TEXT')
        ]
    },
    
    # ========== SRUM (2 Feathers) - Enhanced with specific subtypes ==========
    {
        'name': 'SRUM_ApplicationUsage_CrowEyeFeather',
        'source_db': 'srum_data.db',
        'source_table': 'srum_application_usage',
        'artifact_type': 'SRUM_ApplicationUsage', # Enhanced: specific subtype
        'parent_type': 'SRUM',
        'fallback_columns': [
        ('id', 'INTEGER'), ('timestamp', 'TEXT'), ('app_name', 'TEXT'),
        ('app_path', 'TEXT'), ('user_sid', 'TEXT'), ('user_name', 'TEXT'),
        ('foreground_cycle_time', 'INTEGER'), ('background_cycle_time', 'INTEGER'),
        ('face_time', 'INTEGER'), ('foreground_context_switches', 'INTEGER'),
        ('background_context_switches', 'INTEGER'), ('foreground_bytes_read', 'INTEGER'),
        ('foreground_bytes_written', 'INTEGER'),
        ('foreground_num_read_operations', 'INTEGER'),
        ('foreground_num_write_operations', 'INTEGER'),
        ('foreground_number_of_flushes', 'INTEGER'), ('background_bytes_read', 'INTEGER'),
        ('background_bytes_written', 'INTEGER'),
        ('background_num_read_operations', 'INTEGER'),
        ('background_num_write_operations', 'INTEGER'),
        ('background_number_of_flushes', 'INTEGER')
        ]
    },
    {
        'name': 'SRUM_NetworkDataUsage_CrowEyeFeather',
        'source_db': 'srum_data.db',
        'source_table': 'srum_network_data_usage',
        'artifact_type': 'SRUM_NetworkDataUsage', # Enhanced: specific subtype
        'parent_type': 'SRUM',
        'fallback_columns': [
        ('id', 'INTEGER'), ('timestamp', 'TEXT'), ('app_name', 'TEXT'),
        ('app_path', 'TEXT'), ('user_sid', 'TEXT'), ('user_name', 'TEXT'),
        ('interface_luid', 'INTEGER'), ('l2_profile_id', 'INTEGER'),
        ('bytes_sent', 'INTEGER'), ('bytes_received', 'INTEGER')
        ]
    },
    
    # ========== ShimCache (1 Feather) ==========
    {
        'name': 'ShimCache_CrowEyeFeather',
        'source_db': 'shimcache.db',
        'source_table': 'shimcache_entries',
        # Legacy bookkeeping alias for this table; see
        # BOOKKEEPING_COLUMNS in auto_feather_generator.py for why
        # this is per-table and not a global name.
        'bookkeeping_columns': ['parsed_timestamp'],
        'artifact_type': 'ShimCache',
        'parent_type': 'ShimCache',
        'fallback_columns': [
        ('id', 'INTEGER'), ('filename', 'TEXT'), ('path', 'TEXT'), ('entry_type', 'TEXT'),
        ('package_family_name', 'TEXT'), ('package_version', 'TEXT'),
        ('architecture', 'TEXT'), ('raw_entry', 'TEXT'), ('last_modified', 'TEXT'),
        ('last_modified_readable', 'TEXT'), ('data_size', 'INTEGER'),
        ('entry_size', 'INTEGER'), ('cache_entry_position', 'INTEGER'),
        ('cache_index', 'INTEGER'),
        ('record_id', 'TEXT'), ('shim_flags', 'TEXT'),
        ('entry_hash', 'TEXT'), ('parsed_at', 'TEXT')
        ]
    },


    # ========== Registry keys the engine could not see (14 Feathers) ==========
    # Nine came from the round that added them to the parsers; five were
    # holding evidence with no feather at all - ScheduledTasks among them,
    # which is a top-tier persistence artifact no wing could reach.
    {
        'name': 'StartupApproved_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'startup_approved',
        'artifact_type': 'StartupApproved',
        'parent_type': 'Registry',
        'fallback_columns': [
        ('hive', 'TEXT'), ('scope', 'TEXT'), ('entry_name', 'TEXT'), ('state', 'TEXT'),
        ('state_byte', 'TEXT'), ('disabled_at', 'TEXT'), ('key_path', 'TEXT'),
        ('last_written', 'TEXT'), ('time_basis', 'TEXT'), ('parsed_at', 'TEXT')
        ]
    },
    {
        'name': 'AppPaths_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'app_paths',
        'artifact_type': 'AppPaths',
        'parent_type': 'Registry',
        'fallback_columns': [
        ('app_name', 'TEXT'), ('executable_path', 'TEXT'), ('app_dir', 'TEXT'),
        ('key_path', 'TEXT'), ('last_written', 'TEXT'), ('time_basis', 'TEXT'),
        ('parsed_at', 'TEXT')
        ]
    },
    {
        'name': 'SafeBootServices_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'safe_boot_services',
        'artifact_type': 'SafeBootServices',
        'parent_type': 'Registry',
        'fallback_columns': [
        ('boot_mode', 'TEXT'), ('entry_name', 'TEXT'), ('entry_type', 'TEXT'),
        ('key_path', 'TEXT'), ('last_written', 'TEXT'), ('time_basis', 'TEXT'),
        ('parsed_at', 'TEXT')
        ]
    },
    {
        'name': 'ScheduledTasks_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'ScheduledTasks',
        'artifact_type': 'ScheduledTasks',
        'parent_type': 'Registry',
        'fallback_columns': [
        ('task_path', 'TEXT'), ('task_guid', 'TEXT'), ('command', 'TEXT'),
        ('arguments', 'TEXT'), ('working_dir', 'TEXT'), ('run_context', 'TEXT'),
        ('triggers_index', 'TEXT'), ('task_registered', 'TEXT'), ('last_run', 'TEXT'),
        ('last_completed', 'TEXT'), ('last_result', 'INTEGER'), ('parsed_at', 'TEXT')
        ]
    },
    {
        'name': 'ActiveSetup_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'active_setup',
        'artifact_type': 'ActiveSetup',
        'parent_type': 'Registry',
        'fallback_columns': [
        ('hive', 'TEXT'), ('key_path', 'TEXT'), ('name', 'TEXT'), ('data', 'TEXT'),
        ('data_decoded', 'TEXT'), ('type', 'TEXT'), ('user_name', 'TEXT'),
        ('parsed_at', 'TEXT')
        ]
    },
    {
        'name': 'SharedDLLs_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'shared_dlls',
        'artifact_type': 'SharedDLLs',
        'parent_type': 'Registry',
        'fallback_columns': [
        ('dll_path', 'TEXT'), ('reference_count', 'INTEGER'), ('key_path', 'TEXT'),
        ('last_written', 'TEXT'), ('time_basis', 'TEXT'), ('parsed_at', 'TEXT')
        ]
    },
    {
        'name': 'HIDDevices_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'hid_devices',
        'artifact_type': 'HIDDevices',
        'parent_type': 'Registry',
        'fallback_columns': [
        ('device_id', 'TEXT'), ('instance_id', 'TEXT'), ('device_desc', 'TEXT'),
        ('manufacturer', 'TEXT'), ('service', 'TEXT'), ('key_path', 'TEXT'),
        ('last_written', 'TEXT'), ('time_basis', 'TEXT'), ('parsed_at', 'TEXT')
        ]
    },
    {
        'name': 'NetworkCards_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'network_cards',
        'artifact_type': 'NetworkCards',
        'parent_type': 'Registry',
        'fallback_columns': [
        ('card_index', 'TEXT'), ('description', 'TEXT'), ('service_name', 'TEXT'),
        ('key_path', 'TEXT'), ('last_written', 'TEXT'), ('time_basis', 'TEXT'),
        ('parsed_at', 'TEXT')
        ]
    },
    {
        'name': 'ZoneMap_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'zone_map',
        'artifact_type': 'ZoneMap',
        'parent_type': 'Registry',
        'fallback_columns': [
        ('scope', 'TEXT'), ('host', 'TEXT'), ('protocol', 'TEXT'), ('zone', 'TEXT'),
        ('zone_name', 'TEXT'), ('key_path', 'TEXT'), ('last_written', 'TEXT'),
        ('time_basis', 'TEXT'), ('parsed_at', 'TEXT')
        ]
    },
    {
        'name': 'AppPermissions_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'app_permissions',
        'artifact_type': 'AppPermissions',
        'parent_type': 'Registry',
        'fallback_columns': [
        ('capability', 'TEXT'), ('app', 'TEXT'), ('packaged', 'INTEGER'),
        ('permission', 'TEXT'), ('last_used_start', 'TEXT'), ('last_used_stop', 'TEXT'),
        ('key_path', 'TEXT'), ('last_written', 'TEXT'), ('time_basis', 'TEXT'),
        ('parsed_at', 'TEXT')
        ]
    },
    {
        'name': 'SystemConfiguration_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'system_configuration',
        'artifact_type': 'SystemConfiguration',
        'parent_type': 'Registry',
        'fallback_columns': [
        ('setting', 'TEXT'), ('value_raw', 'TEXT'), ('value_decoded', 'TEXT'),
        ('area', 'TEXT'), ('meaning', 'TEXT'), ('key_path', 'TEXT'),
        ('last_written', 'TEXT'), ('time_basis', 'TEXT'), ('parsed_at', 'TEXT')
        ]
    },
    {
        'name': 'SecurityPosture_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'SecurityPosture',
        'artifact_type': 'SecurityPosture',
        'parent_type': 'Registry',
        'fallback_columns': [
        ('setting', 'TEXT'), ('value_raw', 'TEXT'), ('value_decoded', 'TEXT'),
        ('default_value', 'TEXT'), ('assessment', 'TEXT'), ('meaning', 'TEXT'),
        ('key_path', 'TEXT'), ('last_written', 'TEXT'), ('time_basis', 'TEXT'),
        ('parsed_at', 'TEXT')
        ]
    },
    {
        'name': 'FirewallRules_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'FirewallRules',
        'artifact_type': 'FirewallRules',
        'parent_type': 'Registry',
        'fallback_columns': [
        ('rule_type', 'TEXT'), ('rule_name', 'TEXT'), ('display_name', 'TEXT'),
        ('action', 'TEXT'), ('direction', 'TEXT'), ('enabled', 'TEXT'),
        ('protocol', 'TEXT'), ('local_port', 'TEXT'), ('remote_port', 'TEXT'),
        ('application', 'TEXT'), ('service', 'TEXT'), ('profile', 'TEXT'),
        ('key_path', 'TEXT'), ('last_written', 'TEXT'), ('time_basis', 'TEXT'),
        ('parsed_at', 'TEXT')
        ]
    },
    {
        'name': 'WinevtChannels_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'winevt_channels',
        'artifact_type': 'WinevtChannels',
        'parent_type': 'Registry',
        'fallback_columns': [
        ('channel', 'TEXT'), ('source', 'TEXT'), ('enabled', 'TEXT'), ('max_size', 'TEXT'),
        ('retention', 'TEXT'), ('log_file', 'TEXT'), ('reason', 'TEXT'),
        ('key_path', 'TEXT'), ('last_written', 'TEXT'), ('time_basis', 'TEXT'),
        ('parsed_at', 'TEXT')
        ]
    }
]


def get_feather_mappings() -> List[Dict]:
    """
    Get all Feather generation mappings.
    
    Returns:
        List of 27 Feather mapping dictionaries with enhanced artifact types
    """
    return FEATHER_MAPPINGS


def get_mapping_by_name(feather_name: str) -> Dict:
    """
    Get a specific Feather mapping by name.
    
    Args:
        feather_name: Name of the Feather
        
    Returns:
        Mapping dictionary or None if not found
    """
    for mapping in FEATHER_MAPPINGS:
        if mapping['name'] == feather_name:
            return mapping
    return None


def get_mappings_by_artifact_type(artifact_type: str) -> List[Dict]:
    """
    Get all Feather mappings for a specific artifact type.
    
    Args:
        artifact_type: Artifact type (e.g., "UserAssist", "Registry", "AmCache")
        
    Returns:
        List of matching mapping dictionaries
    """
    # Check both specific artifact_type and parent_type
    matches = []
    for mapping in FEATHER_MAPPINGS:
        if (mapping['artifact_type'] == artifact_type or 
            mapping.get('parent_type') == artifact_type):
            matches.append(mapping)
    return matches


def get_mappings_by_source_db(source_db: str) -> List[Dict]:
    """
    Get all Feather mappings from a specific source database.
    
    Args:
        source_db: Source database filename (e.g., "registry_data.db")
        
    Returns:
        List of matching mapping dictionaries
    """
    return [m for m in FEATHER_MAPPINGS if m['source_db'] == source_db]


def get_all_artifact_types() -> List[str]:
    """
    Get all unique artifact types (both specific and parent types).
    
    Returns:
        List of all artifact type names
    """
    types = set()
    for mapping in FEATHER_MAPPINGS:
        types.add(mapping['artifact_type'])
        if 'parent_type' in mapping:
            types.add(mapping['parent_type'])
    return sorted(list(types))


def get_artifact_types_by_parent(parent_type: str) -> List[str]:
    """
    Get all specific artifact types under a parent type.
    
    Args:
        parent_type: Parent artifact type (e.g., "Registry")
        
    Returns:
        List of specific artifact types under the parent
    """
    subtypes = []
    for mapping in FEATHER_MAPPINGS:
        if mapping.get('parent_type') == parent_type:
            subtypes.append(mapping['artifact_type'])
    return sorted(list(set(subtypes)))


# Enhanced summary statistics
TOTAL_FEATHERS = len(FEATHER_MAPPINGS)

# Updated statistics with enhanced artifact types
FEATHERS_BY_PARENT_TYPE = {
    'AmCache': 3,
    'LNK': 1,
    'Jumplists': 2,
    'Logs': 3,
    'MFT': 1,
    'Prefetch': 1,
    'RecycleBin': 1,
    'Registry': 12,
    'SRUM': 2,
    'ShimCache': 1
}

# New: Specific artifact types count
FEATHERS_BY_SPECIFIC_TYPE = {
    # AmCache subtypes
    'InventoryApplication': 1,
    'InventoryApplicationFile': 1,
    'InventoryApplicationShortcut': 1,
    
    # LNK and Jumplists
    'LNK': 1,
    'AutomaticJumplist': 1,
    'CustomJumplist': 1,
    
    # Log subtypes
    'SecurityLogs': 1,
    'SystemLogs': 1,
    'ApplicationLogs': 1,
    
    # File system
    'MFT': 1,
    'Prefetch': 1,
    'RecycleBin': 1,
    'ShimCache': 1,
    
    # Registry subtypes (12 specific types)
    'BAM': 1,
    'InstalledSoftware': 1,
    'LastSaveMRU': 1,
    'MUICache': 1,
    'OpenSaveMRU': 1,
    'RecentDocs': 1,
    'ShellBags': 1,
    'SystemServices': 1,
    'TypedPaths': 1,
    'WordWheelQuery': 1,
    'UserAssist': 1,
    'AutoStartPrograms': 1,
    
    # SRUM subtypes
    'SRUM_ApplicationUsage': 1,
    'SRUM_NetworkDataUsage': 1
}

# Forensic value categories
HIGH_VALUE_ARTIFACTS = [
    'UserAssist', 'BAM', 'MUICache', 'Prefetch', 'ShimCache',
    'InventoryApplication', 'InventoryApplicationFile', 'SecurityLogs',
    'AutoStartPrograms'
]

MEDIUM_VALUE_ARTIFACTS = [
    'ShellBags', 'RecentDocs', 'OpenSaveMRU', 'LastSaveMRU', 'TypedPaths',
    'WordWheelQuery', 'InstalledSoftware', 'SystemServices', 'SystemLogs',
    'ApplicationLogs', 'SRUM_ApplicationUsage', 'SRUM_NetworkDataUsage',
    'InventoryApplicationShortcut', 'AutomaticJumplist', 'CustomJumplist',
    'LNK', 'MFT', 'RecycleBin'
]
