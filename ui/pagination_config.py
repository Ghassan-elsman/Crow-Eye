"""
Pagination Configuration Manager for Crow Eye
Handles loading and saving pagination preferences per table type.
"""

import json
import os
from pathlib import Path


class PaginationConfig:
    """
    Manages pagination preferences for different table types.
    Preferences are stored in the case configuration or a default config file.
    """
    
    DEFAULT_CONFIG = {
        'mft': {
            'page_size': 1000,
            'current_page': 1
        },
        'usn': {
            'page_size': 1000,
            'current_page': 1
        },
        'correlated': {
            'page_size': 1000,
            'current_page': 1
        },
        'default': {
            'page_size': 1000,
            'current_page': 1
        }
    }
    
    def __init__(self, config_file=None):
        """
        Initialize pagination configuration manager.
        
        Args:
            config_file: Path to configuration file (optional)
        """
        self.config_file = config_file
        # Deep copy to avoid reference issues
        self.config = {}
        for key, value in self.DEFAULT_CONFIG.items():
            self.config[key] = value.copy()
        
        if config_file and os.path.exists(config_file):
            self.load()
    
    def load(self):
        """Load pagination preferences from configuration file."""
        if not self.config_file or not os.path.exists(self.config_file):
            return
        
        try:
            # Check if file is empty
            if os.path.getsize(self.config_file) == 0:
                return
            
            with open(self.config_file, 'r') as f:
                data = json.load(f)
                
            # Load pagination section if it exists
            if 'pagination' in data:
                pagination_data = data['pagination']
                
                # Update config with loaded values
                for table_type in ['mft', 'usn', 'correlated', 'default']:
                    if table_type in pagination_data:
                        self.config[table_type].update(pagination_data[table_type])
                        
        except Exception as e:
            print(f"[PaginationConfig] Error loading configuration: {e}")
    
    def save(self):
        """Save pagination preferences to configuration file."""
        if not self.config_file:
            return
        
        try:
            # Load existing config if it exists
            existing_data = {}
            if os.path.exists(self.config_file) and os.path.getsize(self.config_file) > 0:
                try:
                    with open(self.config_file, 'r') as f:
                        existing_data = json.load(f)
                except json.JSONDecodeError:
                    # File exists but is not valid JSON, start fresh
                    existing_data = {}
            
            # Update pagination section
            existing_data['pagination'] = self.config
            
            # Ensure directory exists
            config_dir = os.path.dirname(self.config_file)
            if config_dir:
                os.makedirs(config_dir, exist_ok=True)
            
            # Save updated config
            with open(self.config_file, 'w') as f:
                json.dump(existing_data, f, indent=2)
                
        except Exception as e:
            print(f"[PaginationConfig] Error saving configuration: {e}")
    
    def get_page_size(self, table_type):
        """
        Get the page size preference for a table type.
        
        Args:
            table_type: Type of table ('mft', 'usn', 'correlated', etc.)
            
        Returns:
            int: Page size preference
        """
        table_type = table_type.lower()
        if table_type in self.config:
            return self.config[table_type].get('page_size', 1000)
        return self.config['default']['page_size']
    
    def set_page_size(self, table_type, page_size):
        """
        Set the page size preference for a table type.
        
        Args:
            table_type: Type of table ('mft', 'usn', 'correlated', etc.)
            page_size: Page size to set
        """
        table_type = table_type.lower()
        if table_type not in self.config:
            self.config[table_type] = self.DEFAULT_CONFIG['default'].copy()
        
        self.config[table_type]['page_size'] = page_size
        self.save()
    
    def get_current_page(self, table_type):
        """
        Get the current page preference for a table type.
        
        Args:
            table_type: Type of table ('mft', 'usn', 'correlated', etc.)
            
        Returns:
            int: Current page preference
        """
        table_type = table_type.lower()
        if table_type in self.config:
            return self.config[table_type].get('current_page', 1)
        return self.config['default']['current_page']
    
    def set_current_page(self, table_type, current_page):
        """
        Set the current page preference for a table type.
        
        Args:
            table_type: Type of table ('mft', 'usn', 'correlated', etc.)
            current_page: Current page to set
        """
        table_type = table_type.lower()
        if table_type not in self.config:
            self.config[table_type] = self.DEFAULT_CONFIG['default'].copy()
        
        self.config[table_type]['current_page'] = current_page
        self.save()
    
    def get_preferences(self, table_type):
        """
        Get all preferences for a table type.
        
        Args:
            table_type: Type of table ('mft', 'usn', 'correlated', etc.)
            
        Returns:
            dict: Preferences dictionary
        """
        table_type = table_type.lower()
        if table_type in self.config:
            return self.config[table_type].copy()
        return self.config['default'].copy()
    
    def set_preferences(self, table_type, preferences):
        """
        Set all preferences for a table type.
        
        Args:
            table_type: Type of table ('mft', 'usn', 'correlated', etc.)
            preferences: Dictionary of preferences
        """
        table_type = table_type.lower()
        if table_type not in self.config:
            self.config[table_type] = self.DEFAULT_CONFIG['default'].copy()
        
        self.config[table_type].update(preferences)
        self.save()
    
    def reset_to_defaults(self, table_type=None):
        """
        Reset preferences to defaults.
        
        Args:
            table_type: Type of table to reset (None to reset all)
        """
        if table_type:
            table_type = table_type.lower()
            if table_type in self.DEFAULT_CONFIG:
                # Create a deep copy to avoid reference issues
                self.config[table_type] = {
                    'page_size': self.DEFAULT_CONFIG[table_type]['page_size'],
                    'current_page': self.DEFAULT_CONFIG[table_type]['current_page']
                }
        else:
            # Reset all table types
            self.config = {}
            for key in self.DEFAULT_CONFIG:
                self.config[key] = {
                    'page_size': self.DEFAULT_CONFIG[key]['page_size'],
                    'current_page': self.DEFAULT_CONFIG[key]['current_page']
                }
        
        self.save()
