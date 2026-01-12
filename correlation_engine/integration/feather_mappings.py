"""
Feather Mappings Configuration

Defines all 27 Feather generation mappings from Crow-Eye parser output.
Each mapping specifies source database, table, artifact type, and column exclusions.
Enhanced with improved artifact type detection and subtype categorization.
"""

from typing import List, Dict, Optional


# Enhanced artifact type mappings with subtypes
ENHANCED_ARTIFACT_TYPES = {
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
        'artifact_type': 'InventoryApplication',  # Enhanced: specific subtype
        'parent_type': 'AmCache',
        'exclude_last_column': False
    },
    {
        'name': 'InventoryApplicationFile_CrowEyeFeather',
        'source_db': 'amcache.db',
        'source_table': 'InventoryApplicationFile',
        'artifact_type': 'InventoryApplicationFile',  # Enhanced: specific subtype
        'parent_type': 'AmCache',
        'exclude_last_column': False
    },
    {
        'name': 'InventoryApplicationShortcut_CrowEyeFeather',
        'source_db': 'amcache.db',
        'source_table': 'InventoryApplicationShortcut',
        'artifact_type': 'InventoryApplicationShortcut',  # Enhanced: specific subtype
        'parent_type': 'AmCache',
        'exclude_last_column': False
    },
    
    # ========== LNK and Jumplists (3 Feathers) ==========
    {
        'name': 'LNK_CrowEyeFeather',
        'source_db': 'LnkDB.db',
        'source_table': 'JLCE',
        'artifact_type': 'LNK',
        'parent_type': 'LNK',
        'exclude_last_column': False,
        'filter': "Artifact = 'lnk'"
    },
    {
        'name': 'AutomaticJumplist_CrowEyeFeather',
        'source_db': 'LnkDB.db',
        'source_table': 'JLCE',
        'artifact_type': 'AutomaticJumplist',  # Enhanced: specific subtype
        'parent_type': 'Jumplists',
        'exclude_last_column': False,
        'filter': "Artifact = 'Automatic JumpList'"
    },
    {
        'name': 'CustomJumplist_CrowEyeFeather',
        'source_db': 'LnkDB.db',
        'source_table': 'Custom_JLCE',
        'artifact_type': 'CustomJumplist',  # Enhanced: specific subtype
        'parent_type': 'Jumplists',
        'exclude_last_column': False
    },
    
    # ========== Event Logs (3 Feathers) ==========
    {
        'name': 'SecurityLogs_CrowEyeFeather',
        'source_db': 'Log_Claw.db',
        'source_table': 'SecurityLogs',
        'artifact_type': 'SecurityLogs',  # Enhanced: specific subtype
        'parent_type': 'Logs',
        'exclude_last_column': False
    },
    {
        'name': 'SystemLogs_CrowEyeFeather',
        'source_db': 'Log_Claw.db',
        'source_table': 'SystemLogs',
        'artifact_type': 'SystemLogs',  # Enhanced: specific subtype
        'parent_type': 'Logs',
        'exclude_last_column': False
    },
    {
        'name': 'ApplicationLogs_CrowEyeFeather',
        'source_db': 'Log_Claw.db',
        'source_table': 'ApplicationLogs',
        'artifact_type': 'ApplicationLogs',  # Enhanced: specific subtype
        'parent_type': 'Logs',
        'exclude_last_column': False
    },
    
    # ========== MFT/USN (1 Feather) ==========
    {
        'name': 'MFT_USN_Correlated_CrowEyeFeather',
        'source_db': 'mft_usn_correlated_analysis.db',
        'source_table': 'mft_usn_correlated',
        'artifact_type': 'MFT',
        'parent_type': 'MFT',
        'exclude_last_column': True  # Exclude created_at parsing timestamp
    },
    
    # ========== Prefetch (1 Feather) ==========
    {
        'name': 'Prefetch_CrowEyeFeather',
        'source_db': 'prefetch_data.db',
        'source_table': 'prefetch_data',
        'artifact_type': 'Prefetch',
        'parent_type': 'Prefetch',
        'exclude_last_column': False
    },
    
    # ========== RecycleBin (1 Feather) ==========
    {
        'name': 'RecycleBin_CrowEyeFeather',
        'source_db': 'recyclebin_analysis.db',
        'source_table': 'recycle_bin_entries',
        'artifact_type': 'RecycleBin',
        'parent_type': 'RecycleBin',
        'exclude_last_column': True  # Exclude parsed_at parsing timestamp
    },
    
    # ========== Registry (12 Feathers) - Enhanced with specific subtypes ==========
    {
        'name': 'BAM_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'BAM',
        'artifact_type': 'BAM',  # Enhanced: specific subtype
        'parent_type': 'Registry',
        'exclude_last_column': True  # Exclude parsing timestamp
    },
    {
        'name': 'InstalledSoftware_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'InstalledSoftware',
        'artifact_type': 'InstalledSoftware',  # Enhanced: specific subtype
        'parent_type': 'Registry',
        'exclude_last_column': True  # Exclude timestamp
    },
    {
        'name': 'LastSaveMRU_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'LastSaveMRU',
        'artifact_type': 'LastSaveMRU',  # Enhanced: specific subtype
        'parent_type': 'Registry',
        'exclude_last_column': True  # Exclude analyzed date
    },
    {
        'name': 'MUICache_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'MUICache',
        'artifact_type': 'MUICache',  # Enhanced: specific subtype
        'parent_type': 'Registry',
        'exclude_last_column': True  # Exclude timestamp
    },
    {
        'name': 'OpenSaveMRU_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'OpenSaveMRU',
        'artifact_type': 'OpenSaveMRU',  # Enhanced: specific subtype
        'parent_type': 'Registry',
        'exclude_last_column': True  # Exclude last column
    },
    {
        'name': 'RecentDocs_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'RecentDocs',
        'artifact_type': 'RecentDocs',  # Enhanced: specific subtype
        'parent_type': 'Registry',
        'exclude_last_column': False
    },
    {
        'name': 'ShellBags_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'Shellbags',
        'artifact_type': 'ShellBags',  # Enhanced: specific subtype
        'parent_type': 'Registry',
        'exclude_last_column': True  # Exclude analyzed date
    },
    {
        'name': 'SystemServices_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'SystemServices',
        'artifact_type': 'SystemServices',  # Enhanced: specific subtype
        'parent_type': 'Registry',
        'exclude_last_column': True  # Exclude timestamp
    },
    {
        'name': 'TypedPaths_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'TypedPaths',
        'artifact_type': 'TypedPaths',  # Enhanced: specific subtype
        'parent_type': 'Registry',
        'exclude_last_column': False
    },
    {
        'name': 'WordWheelQuery_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'WordWheelQuery',
        'artifact_type': 'WordWheelQuery',  # Enhanced: specific subtype
        'parent_type': 'Registry',
        'exclude_last_column': False
    },
    {
        'name': 'UserAssist_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'UserAssist',
        'artifact_type': 'UserAssist',  # Enhanced: specific subtype instead of generic "Registry"
        'parent_type': 'Registry',
        'exclude_last_column': False
    },
    {
        'name': 'AutoStartPrograms_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'AutoStartPrograms',
        'artifact_type': 'AutoStartPrograms',  # Enhanced: specific subtype
        'parent_type': 'Registry',
        'exclude_last_column': True  # Exclude timestamp
    },
    
    # ========== SRUM (2 Feathers) - Enhanced with specific subtypes ==========
    {
        'name': 'SRUM_ApplicationUsage_CrowEyeFeather',
        'source_db': 'srum_data.db',
        'source_table': 'srum_application_usage',
        'artifact_type': 'SRUM_ApplicationUsage',  # Enhanced: specific subtype
        'parent_type': 'SRUM',
        'exclude_last_column': False
    },
    {
        'name': 'SRUM_NetworkDataUsage_CrowEyeFeather',
        'source_db': 'srum_data.db',
        'source_table': 'srum_network_data_usage',
        'artifact_type': 'SRUM_NetworkDataUsage',  # Enhanced: specific subtype
        'parent_type': 'SRUM',
        'exclude_last_column': False
    },
    
    # ========== ShimCache (1 Feather) ==========
    {
        'name': 'ShimCache_CrowEyeFeather',
        'source_db': 'shimcache.db',
        'source_table': 'shimcache_entries',
        'artifact_type': 'ShimCache',
        'parent_type': 'ShimCache',
        'exclude_last_column': True  # Exclude parsed timestamp
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
