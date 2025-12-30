"""
Feather Mappings Configuration

Defines all 27 Feather generation mappings from Crow-Eye parser output.
Each mapping specifies source database, table, artifact type, and column exclusions.
"""

from typing import List, Dict


# Complete list of all 27 Feather generation mappings
FEATHER_MAPPINGS: List[Dict] = [
    # ========== AmCache (3 Feathers) ==========
    {
        'name': 'InventoryApplication_CrowEyeFeather',
        'source_db': 'amcache.db',
        'source_table': 'InventoryApplication',
        'artifact_type': 'AmCache',
        'exclude_last_column': False
    },
    {
        'name': 'InventoryApplicationFile_CrowEyeFeather',
        'source_db': 'amcache.db',
        'source_table': 'InventoryApplicationFile',
        'artifact_type': 'AmCache',
        'exclude_last_column': False
    },
    {
        'name': 'InventoryApplicationShortcut_CrowEyeFeather',
        'source_db': 'amcache.db',
        'source_table': 'InventoryApplicationShortcut',
        'artifact_type': 'AmCache',
        'exclude_last_column': False
    },
    
    # ========== LNK and Jumplists (3 Feathers) ==========
    {
        'name': 'LNK_CrowEyeFeather',
        'source_db': 'LnkDB.db',
        'source_table': 'JLCE',
        'artifact_type': 'LNK',
        'exclude_last_column': False,
        'filter': "Artifact = 'lnk'"
    },
    {
        'name': 'AutomaticJumplist_CrowEyeFeather',
        'source_db': 'LnkDB.db',
        'source_table': 'JLCE',
        'artifact_type': 'Jumplists',
        'exclude_last_column': False,
        'filter': "Artifact = 'Automatic JumpList'"
    },
    {
        'name': 'CustomJumplist_CrowEyeFeather',
        'source_db': 'LnkDB.db',
        'source_table': 'Custom_JLCE',
        'artifact_type': 'Jumplists',
        'exclude_last_column': False
    },
    
    # ========== Event Logs (3 Feathers) ==========
    {
        'name': 'SecurityLogs_CrowEyeFeather',
        'source_db': 'Log_Claw.db',
        'source_table': 'SecurityLogs',
        'artifact_type': 'Logs',
        'exclude_last_column': False
    },
    {
        'name': 'SystemLogs_CrowEyeFeather',
        'source_db': 'Log_Claw.db',
        'source_table': 'SystemLogs',
        'artifact_type': 'Logs',
        'exclude_last_column': False
    },
    {
        'name': 'ApplicationLogs_CrowEyeFeather',
        'source_db': 'Log_Claw.db',
        'source_table': 'ApplicationLogs',
        'artifact_type': 'Logs',
        'exclude_last_column': False
    },
    
    # ========== MFT/USN (1 Feather) ==========
    {
        'name': 'MFT_USN_Correlated_CrowEyeFeather',
        'source_db': 'mft_usn_correlated_analysis.db',
        'source_table': 'mft_usn_correlated',
        'artifact_type': 'MFT',
        'exclude_last_column': True  # Exclude created_at parsing timestamp
    },
    
    # ========== Prefetch (1 Feather) ==========
    {
        'name': 'Prefetch_CrowEyeFeather',
        'source_db': 'prefetch_data.db',
        'source_table': 'prefetch_data',
        'artifact_type': 'Prefetch',
        'exclude_last_column': False
    },
    
    # ========== RecycleBin (1 Feather) ==========
    {
        'name': 'RecycleBin_CrowEyeFeather',
        'source_db': 'recyclebin_analysis.db',
        'source_table': 'recycle_bin_entries',
        'artifact_type': 'RecycleBin',
        'exclude_last_column': True  # Exclude parsed_at parsing timestamp
    },
    
    # ========== Registry (12 Feathers) ==========
    {
        'name': 'BAM_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'BAM',
        'artifact_type': 'Registry',
        'exclude_last_column': True  # Exclude parsing timestamp
    },
    {
        'name': 'InstalledSoftware_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'InstalledSoftware',
        'artifact_type': 'Registry',
        'exclude_last_column': True  # Exclude timestamp
    },
    {
        'name': 'LastSaveMRU_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'LastSaveMRU',
        'artifact_type': 'Registry',
        'exclude_last_column': True  # Exclude analyzed date
    },
    {
        'name': 'MUICache_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'MUICache',
        'artifact_type': 'Registry',
        'exclude_last_column': True  # Exclude timestamp
    },
    {
        'name': 'OpenSaveMRU_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'OpenSaveMRU',
        'artifact_type': 'Registry',
        'exclude_last_column': True  # Exclude last column
    },
    {
        'name': 'RecentDocs_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'RecentDocs',
        'artifact_type': 'Registry',
        'exclude_last_column': False
    },
    {
        'name': 'ShellBags_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'Shellbags',
        'artifact_type': 'Registry',
        'exclude_last_column': True  # Exclude analyzed date
    },
    {
        'name': 'SystemServices_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'SystemServices',
        'artifact_type': 'Registry',
        'exclude_last_column': True  # Exclude timestamp
    },
    {
        'name': 'TypedPaths_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'TypedPaths',
        'artifact_type': 'Registry',
        'exclude_last_column': False
    },
    {
        'name': 'WordWheelQuery_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'WordWheelQuery',
        'artifact_type': 'Registry',
        'exclude_last_column': False
    },
    {
        'name': 'UserAssist_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'UserAssist',
        'artifact_type': 'Registry',
        'exclude_last_column': False
    },
    {
        'name': 'AutoStartPrograms_CrowEyeFeather',
        'source_db': 'registry_data.db',
        'source_table': 'AutoStartPrograms',
        'artifact_type': 'Registry',
        'exclude_last_column': True  # Exclude timestamp
    },
    
    # ========== SRUM (2 Feathers) ==========
    {
        'name': 'SRUM_ApplicationUsage_CrowEyeFeather',
        'source_db': 'srum_data.db',
        'source_table': 'srum_application_usage',
        'artifact_type': 'SRUM',
        'exclude_last_column': False
    },
    {
        'name': 'SRUM_NetworkDataUsage_CrowEyeFeather',
        'source_db': 'srum_data.db',
        'source_table': 'srum_network_data_usage',
        'artifact_type': 'SRUM',
        'exclude_last_column': False
    },
    
    # ========== ShimCache (1 Feather) ==========
    {
        'name': 'ShimCache_CrowEyeFeather',
        'source_db': 'shimcache.db',
        'source_table': 'shimcache_entries',
        'artifact_type': 'ShimCache',
        'exclude_last_column': True  # Exclude parsed timestamp
    }
]


def get_feather_mappings() -> List[Dict]:
    """
    Get all Feather generation mappings.
    
    Returns:
        List of 27 Feather mapping dictionaries
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
        artifact_type: Artifact type (e.g., "Registry", "AmCache")
        
    Returns:
        List of matching mapping dictionaries
    """
    return [m for m in FEATHER_MAPPINGS if m['artifact_type'] == artifact_type]


def get_mappings_by_source_db(source_db: str) -> List[Dict]:
    """
    Get all Feather mappings from a specific source database.
    
    Args:
        source_db: Source database filename (e.g., "Registry.db")
        
    Returns:
        List of matching mapping dictionaries
    """
    return [m for m in FEATHER_MAPPINGS if m['source_db'] == source_db]


# Summary statistics
TOTAL_FEATHERS = len(FEATHER_MAPPINGS)
FEATHERS_BY_TYPE = {
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
