"""
SRUM Application Name Resolver
================================

This module provides functionality to resolve SRUM application IDs to human-readable
application names. SRUM (System Resource Usage Monitor) stores application information
using numeric IDs that reference entries in the SruDbIdMapTable.

The resolver provides:
- Lookup table for common Windows application IDs
- Caching for resolved names to improve performance
- Fallback to ID display when name is not found
- Option to show IDs or names based on user preference

Author: Crow Eye Timeline Feature
Version: 1.0
"""

import logging
from typing import Dict, Optional

# Configure logger
logger = logging.getLogger(__name__)


class SrumAppResolver:
    """
    Resolves SRUM application IDs to human-readable names.
    
    This class maintains a lookup table of common Windows application IDs
    and provides caching for resolved names to improve performance.
    """
    
    # Common Windows SRUM application ID mappings
    # These are typical IDs found in Windows SRUM databases
    # Format: ID -> Application Name
    COMMON_APP_IDS = {
        # System and Windows components
        '1': 'System',
        '2': 'Registry',
        '3': 'Idle',
        '4': 'Memory Compression',
        
        # Common Windows applications
        '28116': 'Microsoft Edge',
        '28117': 'Microsoft Edge (WebView)',
        '28118': 'Microsoft Edge (Background)',
        
        # Office applications
        '10000': 'Microsoft Word',
        '10001': 'Microsoft Excel',
        '10002': 'Microsoft PowerPoint',
        '10003': 'Microsoft Outlook',
        '10004': 'Microsoft OneNote',
        '10005': 'Microsoft Access',
        '10006': 'Microsoft Publisher',
        
        # Windows built-in apps
        '20000': 'Windows Explorer',
        '20001': 'Windows Search',
        '20002': 'Windows Defender',
        '20003': 'Windows Update',
        '20004': 'Windows Store',
        '20005': 'Windows Settings',
        '20006': 'Windows Calculator',
        '20007': 'Windows Notepad',
        '20008': 'Windows Paint',
        '20009': 'Windows Photos',
        '20010': 'Windows Mail',
        '20011': 'Windows Calendar',
        '20012': 'Windows Maps',
        '20013': 'Windows Camera',
        '20014': 'Windows Alarms',
        '20015': 'Windows Weather',
        '20016': 'Windows News',
        '20017': 'Windows Sports',
        '20018': 'Windows Finance',
        '20019': 'Windows Food & Drink',
        '20020': 'Windows Health & Fitness',
        '20021': 'Windows Travel',
        
        # Browsers
        '30000': 'Google Chrome',
        '30001': 'Mozilla Firefox',
        '30002': 'Opera',
        '30003': 'Safari',
        '30004': 'Brave',
        
        # Common third-party applications
        '40000': 'Adobe Acrobat Reader',
        '40001': 'Adobe Photoshop',
        '40002': 'VLC Media Player',
        '40003': 'Spotify',
        '40004': 'Discord',
        '40005': 'Slack',
        '40006': 'Zoom',
        '40007': 'Teams',
        '40008': 'Skype',
        '40009': 'Steam',
        '40010': 'Epic Games Launcher',
        
        # Development tools
        '50000': 'Visual Studio Code',
        '50001': 'Visual Studio',
        '50002': 'PyCharm',
        '50003': 'IntelliJ IDEA',
        '50004': 'Eclipse',
        '50005': 'Sublime Text',
        '50006': 'Notepad++',
        '50007': 'Git',
        '50008': 'Docker',
        '50009': 'VirtualBox',
        '50010': 'VMware',
    }
    
    # User SID mappings (common Windows user SIDs)
    COMMON_USER_SIDS = {
        '449': 'SYSTEM',
        '450': 'LOCAL SERVICE',
        '451': 'NETWORK SERVICE',
        '500': 'Administrator',
        '501': 'Guest',
        '503': 'DefaultAccount',
    }
    
    def __init__(self):
        """Initialize the SRUM app resolver with empty cache."""
        self._name_cache: Dict[str, str] = {}
        self._user_cache: Dict[str, str] = {}
        self._show_ids = False  # Default to showing names
        
        logger.info("SrumAppResolver initialized")
    
    def resolve_app_name(self, app_id: str, app_path: Optional[str] = None) -> str:
        """
        Resolve an application ID to a human-readable name.
        
        This method attempts to resolve the app ID using:
        1. Cache (if previously resolved)
        2. Common app ID lookup table
        3. App path extraction (if available)
        4. Fallback to ID display
        
        Args:
            app_id: The SRUM application ID (as string)
            app_path: Optional application path that might contain the ID
        
        Returns:
            str: Resolved application name or formatted ID
        """
        if not app_id:
            return 'Unknown'
        
        # Convert to string if needed
        app_id_str = str(app_id)
        
        # Check cache first
        if app_id_str in self._name_cache:
            return self._format_result(app_id_str, self._name_cache[app_id_str])
        
        # Try common app ID lookup
        if app_id_str in self.COMMON_APP_IDS:
            app_name = self.COMMON_APP_IDS[app_id_str]
            self._name_cache[app_id_str] = app_name
            return self._format_result(app_id_str, app_name)
        
        # Try to extract name from app_path if available
        if app_path and app_path != app_id_str:
            # If app_path looks like a path, extract the executable name
            if '\\' in app_path or '/' in app_path:
                import os
                app_name = os.path.basename(app_path)
                if app_name and app_name != app_id_str:
                    self._name_cache[app_id_str] = app_name
                    return self._format_result(app_id_str, app_name)
        
        # Fallback: return formatted ID
        fallback_name = f"App ID {app_id_str}"
        self._name_cache[app_id_str] = fallback_name
        return self._format_result(app_id_str, fallback_name)
    
    def resolve_user_name(self, user_sid: str, user_name: Optional[str] = None) -> str:
        """
        Resolve a user SID to a human-readable name.
        
        Args:
            user_sid: The user SID (as string)
            user_name: Optional user name from database
        
        Returns:
            str: Resolved user name or formatted SID
        """
        if not user_sid:
            return 'Unknown'
        
        # Convert to string if needed
        user_sid_str = str(user_sid)
        
        # Check cache first
        if user_sid_str in self._user_cache:
            return self._format_result(user_sid_str, self._user_cache[user_sid_str])
        
        # If user_name is provided and looks valid (not a number), use it
        if user_name and user_name != user_sid_str and not user_name.isdigit():
            self._user_cache[user_sid_str] = user_name
            return self._format_result(user_sid_str, user_name)
        
        # Try common user SID lookup
        if user_sid_str in self.COMMON_USER_SIDS:
            resolved_name = self.COMMON_USER_SIDS[user_sid_str]
            self._user_cache[user_sid_str] = resolved_name
            return self._format_result(user_sid_str, resolved_name)
        
        # Fallback: return formatted SID
        fallback_name = f"User SID {user_sid_str}"
        self._user_cache[user_sid_str] = fallback_name
        return self._format_result(user_sid_str, fallback_name)
    
    def _format_result(self, id_value: str, name: str) -> str:
        """
        Format the result based on show_ids preference.
        
        Args:
            id_value: The original ID value
            name: The resolved name
        
        Returns:
            str: Formatted result
        """
        if self._show_ids:
            # Show both name and ID
            if name.startswith('App ID ') or name.startswith('User SID '):
                # Already formatted as ID, just return it
                return name
            else:
                # Show name with ID in parentheses
                return f"{name} ({id_value})"
        else:
            # Show name only
            return name
    
    def set_show_ids(self, show_ids: bool):
        """
        Set whether to show IDs alongside names.
        
        Args:
            show_ids: If True, show both name and ID; if False, show name only
        """
        self._show_ids = show_ids
        logger.info(f"Show IDs set to: {show_ids}")
    
    def get_show_ids(self) -> bool:
        """
        Get current show_ids setting.
        
        Returns:
            bool: Current show_ids value
        """
        return self._show_ids
    
    def add_custom_mapping(self, app_id: str, app_name: str):
        """
        Add a custom application ID to name mapping.
        
        This allows users to add their own mappings for applications
        not in the common lookup table.
        
        Args:
            app_id: The application ID
            app_name: The application name
        """
        app_id_str = str(app_id)
        self._name_cache[app_id_str] = app_name
        logger.info(f"Added custom mapping: {app_id_str} -> {app_name}")
    
    def add_custom_user_mapping(self, user_sid: str, user_name: str):
        """
        Add a custom user SID to name mapping.
        
        Args:
            user_sid: The user SID
            user_name: The user name
        """
        user_sid_str = str(user_sid)
        self._user_cache[user_sid_str] = user_name
        logger.info(f"Added custom user mapping: {user_sid_str} -> {user_name}")
    
    def clear_cache(self):
        """Clear the resolution cache."""
        self._name_cache.clear()
        self._user_cache.clear()
        logger.info("Resolution cache cleared")
    
    def get_cache_stats(self) -> Dict[str, int]:
        """
        Get cache statistics.
        
        Returns:
            Dict[str, int]: Dictionary with cache statistics
        """
        return {
            'app_cache_size': len(self._name_cache),
            'user_cache_size': len(self._user_cache),
            'total_cached': len(self._name_cache) + len(self._user_cache)
        }
