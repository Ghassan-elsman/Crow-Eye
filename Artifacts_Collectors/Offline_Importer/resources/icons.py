"""
Icon definitions for the Offline Artifact Importer GUI.

This module provides text-based icons and emoji representations for different
artifact types and status indicators. These can be used in the GUI without
requiring external image files.

Author: Crow-eye Forensics
License: MIT
"""

# ============================================================================
# Artifact Type Icons (Task 14.1)
# ============================================================================

ARTIFACT_ICONS = {
    'Registry': '📋',  # Registry hives
    'Prefetch': '📄',  # Prefetch files
    'link_jumplist': '📎',  # Jump Lists
    'MFT': '📁',  # MFT files
    'USN': '📝',  # USN Journal
    'RecycleBin': '🗑️',  # Recycle Bin
    'AmCache': '💾',  # AmCache
    'Unknown': '❓',  # Unknown artifact type
    'All Types': '📦',  # All types
}

# Alternative text-based icons (for systems without emoji support)
ARTIFACT_ICONS_TEXT = {
    'Registry': '[REG]',
    'Prefetch': '[PF]',
    'link_jumplist': '[JL]',
    'MFT': '[MFT]',
    'USN': '[USN]',
    'RecycleBin': '[RB]',
    'AmCache': '[AMC]',
    'Unknown': '[?]',
    'All Types': '[ALL]',
}

# ============================================================================
# Status Icons (Task 14.3)
# ============================================================================

STATUS_ICONS = {
    'success': '✓',  # Successful operation
    'failed': '✗',  # Failed operation
    'warning': '⚠',  # Warning
    'info': 'ℹ',  # Information
    'collecting': '⟳',  # Collection in progress
    'idle': '○',  # Idle state
    'complete': '✓',  # Complete
}

# Alternative text-based status icons
STATUS_ICONS_TEXT = {
    'success': '[OK]',
    'failed': '[X]',
    'warning': '[!]',
    'info': '[i]',
    'collecting': '[~]',
    'idle': '[ ]',
    'complete': '[✓]',
}

# ============================================================================
# Application Icon (Task 14.2)
# ============================================================================

APP_ICON = '🔍'  # Magnifying glass for forensic investigation
APP_ICON_TEXT = '[CROW-EYE]'

# ============================================================================
# Color Definitions (Task 14.5)
# ============================================================================

class IconColors:
    """Color definitions for icons and UI elements"""
    
    # Status colors
    SUCCESS = '#10B981'  # Green
    ERROR = '#EF4444'  # Red
    WARNING = '#F59E0B'  # Amber
    INFO = '#3B82F6'  # Blue
    
    # Artifact type colors
    REGISTRY = '#8B5CF6'  # Purple
    PREFETCH = '#F59E0B'  # Amber
    JUMPLISTS = '#06B6D4'  # Cyan
    MFT = '#10B981'  # Green
    USN = '#6366F1'  # Indigo
    RECYCLEBIN = '#EF4444'  # Red
    AMCACHE = '#EC4899'  # Pink
    UNKNOWN = '#6B7280'  # Gray

# ============================================================================
# Helper Functions
# ============================================================================

def get_artifact_icon(artifact_type: str, use_emoji: bool = True) -> str:
    """
    Get icon for artifact type.
    
    Args:
        artifact_type: Type of artifact
        use_emoji: Whether to use emoji (True) or text (False)
        
    Returns:
        Icon string
    """
    icons = ARTIFACT_ICONS if use_emoji else ARTIFACT_ICONS_TEXT
    return icons.get(artifact_type, icons.get('Unknown', '?'))

def get_status_icon(status: str, use_emoji: bool = True) -> str:
    """
    Get icon for status.
    
    Args:
        status: Status type
        use_emoji: Whether to use emoji (True) or text (False)
        
    Returns:
        Icon string
    """
    icons = STATUS_ICONS if use_emoji else STATUS_ICONS_TEXT
    return icons.get(status, icons.get('info', 'i'))

def get_artifact_color(artifact_type: str) -> str:
    """
    Get color for artifact type.
    
    Args:
        artifact_type: Type of artifact
        
    Returns:
        Hex color string
    """
    color_map = {
        'Registry': IconColors.REGISTRY,
        'Prefetch': IconColors.PREFETCH,
        'link_jumplist': IconColors.JUMPLISTS,
        'MFT': IconColors.MFT,
        'USN': IconColors.USN,
        'RecycleBin': IconColors.RECYCLEBIN,
        'AmCache': IconColors.AMCACHE,
    }
    return color_map.get(artifact_type, IconColors.UNKNOWN)

def get_status_color(status: str) -> str:
    """
    Get color for status.
    
    Args:
        status: Status type
        
    Returns:
        Hex color string
    """
    color_map = {
        'success': IconColors.SUCCESS,
        'failed': IconColors.ERROR,
        'warning': IconColors.WARNING,
        'info': IconColors.INFO,
    }
    return color_map.get(status, IconColors.INFO)
