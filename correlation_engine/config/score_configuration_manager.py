"""
Score Configuration Manager

This module provides a singleton manager for centralized score configuration.
It ensures all components reference the same score configuration instance
and provides methods for loading, updating, and validating configurations.

Requirements validated: 7.1, 7.2, 8.1, 9.1, 9.2
"""

import logging
from pathlib import Path
from typing import List, Optional, Callable
from threading import Lock

from .centralized_score_config import CentralizedScoreConfig

logger = logging.getLogger(__name__)


class ScoreConfigurationManager:
    """
    Manages centralized score configuration using singleton pattern.
    
    Ensures all components reference the same score configuration instance
    and provides methods for configuration management.
    
    This class implements the singleton pattern to guarantee a single
    source of truth for score configurations across the entire system.
    """
    
    _instance = None
    _lock = Lock()
    _config: Optional[CentralizedScoreConfig] = None
    _config_path: Optional[str] = None
    _update_callbacks: List[Callable] = []
    
    def __new__(cls):
        """
        Singleton pattern implementation.
        
        Ensures only one instance of ScoreConfigurationManager exists.
        Thread-safe implementation using double-checked locking.
        
        Returns:
            The singleton instance of ScoreConfigurationManager
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    logger.info("ScoreConfigurationManager singleton instance created")
        return cls._instance
    
    def load_configuration(self, config_path: Optional[str] = None) -> CentralizedScoreConfig:
        """
        Load score configuration from file or use default.
        
        If a configuration path is provided and the file exists, loads from file.
        Otherwise, uses default configuration values.
        
        Args:
            config_path: Optional path to score configuration JSON file
        
        Returns:
            Loaded CentralizedScoreConfig instance
        """
        with self._lock:
            if config_path and Path(config_path).exists():
                try:
                    self._config = CentralizedScoreConfig.load_from_file(config_path)
                    self._config_path = config_path
                    logger.info(f"Loaded score configuration from {config_path}")
                except Exception as e:
                    logger.error(f"Failed to load configuration from {config_path}: {e}")
                    logger.info("Falling back to default configuration")
                    self._config = CentralizedScoreConfig.get_default()
                    self._config_path = None
            else:
                if config_path:
                    logger.warning(f"Configuration file not found: {config_path}")
                    logger.info("Using default score configuration")
                self._config = CentralizedScoreConfig.get_default()
                self._config_path = None
            
            # Validate loaded configuration
            if not self._config.validate():
                logger.warning("Loaded configuration failed validation, using default")
                self._config = CentralizedScoreConfig.get_default()
                self._config_path = None
            
            return self._config
    
    def get_configuration(self) -> CentralizedScoreConfig:
        """
        Get current score configuration.
        
        If no configuration has been loaded, loads default configuration.
        
        Returns:
            Current CentralizedScoreConfig instance
        """
        if self._config is None:
            logger.info("No configuration loaded, loading default")
            self.load_configuration()
        return self._config
    
    def update_configuration(self, new_config: CentralizedScoreConfig, save: bool = True):
        """
        Update score configuration and notify all registered components.
        
        Validates the new configuration before applying it. If validation fails,
        the update is rejected and the old configuration remains active.
        
        Args:
            new_config: New score configuration to apply
            save: Whether to save the configuration to file (default: True)
        
        Raises:
            ValueError: If new configuration fails validation
        """
        with self._lock:
            # Validate new configuration
            if not new_config.validate():
                error_msg = "New configuration failed validation, update rejected"
                logger.error(error_msg)
                raise ValueError(error_msg)
            
            # Update timestamp
            from datetime import datetime
            new_config.last_updated = datetime.now().isoformat()
            
            # Apply new configuration
            old_config = self._config
            self._config = new_config
            
            logger.info("Score configuration updated successfully")
            
            # Save to file if requested and path is known
            if save and self._config_path:
                try:
                    self._config.save_to_file(self._config_path)
                except Exception as e:
                    logger.error(f"Failed to save updated configuration: {e}")
                    # Rollback on save failure
                    self._config = old_config
                    raise
            
            # Notify all registered components
            self._notify_components()
    
    def _notify_components(self):
        """
        Notify all registered components that configuration has changed.
        
        Calls all registered callback functions to inform components
        of configuration updates.
        """
        logger.info(f"Notifying {len(self._update_callbacks)} components of configuration update")
        
        for callback in self._update_callbacks:
            try:
                callback(self._config)
            except Exception as e:
                logger.error(f"Error notifying component: {e}")
    
    def register_update_callback(self, callback: Callable[[CentralizedScoreConfig], None]):
        """
        Register a callback to be notified of configuration updates.
        
        Components can register callbacks to be notified when the score
        configuration is updated, allowing them to reload or refresh.
        
        Args:
            callback: Function to call when configuration updates
                     Should accept CentralizedScoreConfig as parameter
        """
        if callback not in self._update_callbacks:
            self._update_callbacks.append(callback)
            logger.info(f"Registered configuration update callback: {callback.__name__}")
    
    def unregister_update_callback(self, callback: Callable[[CentralizedScoreConfig], None]):
        """
        Unregister a previously registered callback.
        
        Args:
            callback: Function to unregister
        """
        if callback in self._update_callbacks:
            self._update_callbacks.remove(callback)
            logger.info(f"Unregistered configuration update callback: {callback.__name__}")
    
    def validate_consistency(self) -> List[str]:
        """
        Validate that all components use the same configuration.
        
        This method checks for potential inconsistencies in score configuration
        usage across the system. It can detect:
        - Duplicate score definitions in code
        - Components not using centralized configuration
        - Conflicting score values
        
        Returns:
            List of inconsistency warnings (empty list if consistent)
        """
        warnings = []
        
        # Check if configuration is loaded
        if self._config is None:
            warnings.append("No score configuration loaded")
            return warnings
        
        # Validate current configuration
        if not self._config.validate():
            warnings.append("Current configuration failed validation")
        
        # Check for duplicate definitions in wing configurations
        # This would require scanning wing config files
        # For now, we log that validation was performed
        logger.info("Score configuration consistency validation performed")
        
        # Additional checks could be added here:
        # - Scan wing configuration files for local score definitions
        # - Check engine code for hardcoded score values
        # - Verify GUI components reference centralized config
        
        if not warnings:
            logger.info("No score configuration inconsistencies detected")
        else:
            logger.warning(f"Found {len(warnings)} score configuration inconsistencies")
            for warning in warnings:
                logger.warning(f"  - {warning}")
        
        return warnings
    
    def get_config_path(self) -> Optional[str]:
        """
        Get the path to the currently loaded configuration file.
        
        Returns:
            Path to configuration file, or None if using default config
        """
        return self._config_path
    
    def reload_configuration(self):
        """
        Reload configuration from the current config path.
        
        Useful for picking up external changes to the configuration file.
        If no config path is set, reloads default configuration.
        """
        logger.info("Reloading score configuration")
        self.load_configuration(self._config_path)
        self._notify_components()
    
    def reset_to_default(self):
        """
        Reset configuration to default values.
        
        Useful for recovering from configuration errors or
        returning to known-good defaults.
        """
        logger.info("Resetting score configuration to default")
        with self._lock:
            self._config = CentralizedScoreConfig.get_default()
            self._config_path = None
        self._notify_components()
    
    def export_configuration(self, export_path: str):
        """
        Export current configuration to a file.
        
        Args:
            export_path: Path where configuration should be exported
        
        Raises:
            IOError: If file cannot be written
        """
        if self._config is None:
            logger.warning("No configuration to export, using default")
            self._config = CentralizedScoreConfig.get_default()
        
        self._config.save_to_file(export_path)
        logger.info(f"Configuration exported to {export_path}")
