"""
Configuration Change Handler

Handles configuration changes and applies them to correlation engines and other components.
Provides a centralized way to notify components when configuration settings change.
"""

import logging
from typing import Dict, List, Callable, Any
from dataclasses import dataclass

from .integrated_configuration_manager import IntegratedConfiguration

logger = logging.getLogger(__name__)


@dataclass
class ConfigurationChangeEvent:
    """Event data for configuration changes"""
    old_config: IntegratedConfiguration
    new_config: IntegratedConfiguration
    changed_sections: List[str]
    timestamp: str


class ConfigurationChangeHandler:
    """
    Handles configuration changes and notifies registered components.
    
    Provides a centralized system for managing configuration changes
    and ensuring all components are updated when settings change.
    """
    
    def __init__(self):
        """Initialize configuration change handler"""
        self.listeners: Dict[str, List[Callable]] = {
            'semantic_mapping': [],
            'weighted_scoring': [],
            'progress_tracking': [],
            'engine_selection': [],
            'case_specific': [],
            'all': []  # Listeners that want all changes
        }
        
        self.current_config: IntegratedConfiguration = None
    
    def register_listener(self, section: str, callback: Callable[[ConfigurationChangeEvent], None]):
        """
        Register a listener for configuration changes.
        
        Args:
            section: Configuration section to listen for ('semantic_mapping', 'weighted_scoring', 
                    'progress_tracking', 'engine_selection', 'case_specific', or 'all')
            callback: Function to call when configuration changes
        """
        if section not in self.listeners:
            logger.warning(f"Unknown configuration section: {section}")
            return
        
        self.listeners[section].append(callback)
        logger.info(f"Registered configuration listener for section: {section}")
    
    def unregister_listener(self, section: str, callback: Callable):
        """
        Unregister a configuration change listener.
        
        Args:
            section: Configuration section
            callback: Callback function to remove
        """
        if section in self.listeners and callback in self.listeners[section]:
            self.listeners[section].remove(callback)
            logger.info(f"Unregistered configuration listener for section: {section}")
    
    def handle_configuration_change(self, old_config: IntegratedConfiguration, new_config: IntegratedConfiguration):
        """
        Handle a configuration change and notify relevant listeners.
        
        Args:
            old_config: Previous configuration
            new_config: New configuration
        """
        try:
            # Determine which sections changed
            changed_sections = self._detect_changed_sections(old_config, new_config)
            
            if not changed_sections:
                logger.info("No configuration changes detected")
                return
            
            # Create change event
            from datetime import datetime
            event = ConfigurationChangeEvent(
                old_config=old_config,
                new_config=new_config,
                changed_sections=changed_sections,
                timestamp=datetime.now().isoformat()
            )
            
            # Update current config
            self.current_config = new_config
            
            # Notify listeners
            self._notify_listeners(event)
            
            logger.info(f"Configuration change handled: {', '.join(changed_sections)}")
            
        except Exception as e:
            logger.error(f"Failed to handle configuration change: {e}")
    
    def _detect_changed_sections(self, old_config: IntegratedConfiguration, new_config: IntegratedConfiguration) -> List[str]:
        """
        Detect which configuration sections have changed.
        
        Args:
            old_config: Previous configuration
            new_config: New configuration
            
        Returns:
            List of changed section names
        """
        changed_sections = []
        
        # Check semantic mapping changes
        if old_config.semantic_mapping != new_config.semantic_mapping:
            changed_sections.append('semantic_mapping')
        
        # Check weighted scoring changes
        if old_config.weighted_scoring != new_config.weighted_scoring:
            changed_sections.append('weighted_scoring')
        
        # Check progress tracking changes
        if old_config.progress_tracking != new_config.progress_tracking:
            changed_sections.append('progress_tracking')
        
        # Check engine selection changes
        if old_config.engine_selection != new_config.engine_selection:
            changed_sections.append('engine_selection')
        
        # Check case-specific changes
        if old_config.case_specific != new_config.case_specific:
            changed_sections.append('case_specific')
        
        return changed_sections
    
    def _notify_listeners(self, event: ConfigurationChangeEvent):
        """
        Notify all relevant listeners of configuration changes.
        
        Args:
            event: Configuration change event
        """
        # Notify section-specific listeners
        for section in event.changed_sections:
            if section in self.listeners:
                for callback in self.listeners[section]:
                    try:
                        callback(event)
                    except Exception as e:
                        logger.error(f"Configuration listener failed for section {section}: {e}")
        
        # Notify 'all' listeners
        for callback in self.listeners['all']:
            try:
                callback(event)
            except Exception as e:
                logger.error(f"Configuration listener failed for 'all' section: {e}")
    
    def apply_configuration_to_engines(self, new_config: IntegratedConfiguration):
        """
        Apply configuration changes to correlation engines.
        
        Args:
            new_config: New configuration to apply
        """
        try:
            # This method will be called by correlation engines to get updated configuration
            # The actual application is handled by the engines themselves through listeners
            
            logger.info("Configuration applied to engines")
            
        except Exception as e:
            logger.error(f"Failed to apply configuration to engines: {e}")
    
    def get_current_config(self) -> IntegratedConfiguration:
        """
        Get current configuration.
        
        Returns:
            Current IntegratedConfiguration object
        """
        return self.current_config
    
    def validate_configuration_change(self, old_config: IntegratedConfiguration, new_config: IntegratedConfiguration) -> Dict[str, Any]:
        """
        Validate a configuration change before applying it.
        
        Args:
            old_config: Previous configuration
            new_config: New configuration
            
        Returns:
            Dictionary with validation results
        """
        validation_result = {
            'valid': True,
            'warnings': [],
            'errors': [],
            'impact_assessment': {}
        }
        
        try:
            # Check for potentially disruptive changes
            changed_sections = self._detect_changed_sections(old_config, new_config)
            
            for section in changed_sections:
                impact = self._assess_change_impact(section, old_config, new_config)
                validation_result['impact_assessment'][section] = impact
                
                if impact['severity'] == 'high':
                    validation_result['warnings'].append(
                        f"High impact change in {section}: {impact['description']}"
                    )
            
            # Check for configuration conflicts
            conflicts = self._check_configuration_conflicts(new_config)
            if conflicts:
                validation_result['warnings'].extend(conflicts)
            
        except Exception as e:
            validation_result['valid'] = False
            validation_result['errors'].append(f"Validation failed: {e}")
        
        return validation_result
    
    def _assess_change_impact(self, section: str, old_config: IntegratedConfiguration, new_config: IntegratedConfiguration) -> Dict[str, Any]:
        """
        Assess the impact of a configuration change.
        
        Args:
            section: Configuration section that changed
            old_config: Previous configuration
            new_config: New configuration
            
        Returns:
            Dictionary with impact assessment
        """
        impact = {
            'severity': 'low',
            'description': 'Minor configuration change',
            'requires_restart': False,
            'affects_running_operations': False
        }
        
        if section == 'semantic_mapping':
            old_enabled = old_config.semantic_mapping.enabled
            new_enabled = new_config.semantic_mapping.enabled
            
            if old_enabled != new_enabled:
                impact['severity'] = 'medium'
                impact['description'] = f"Semantic mapping {'enabled' if new_enabled else 'disabled'}"
                impact['affects_running_operations'] = True
        
        elif section == 'weighted_scoring':
            old_enabled = old_config.weighted_scoring.enabled
            new_enabled = new_config.weighted_scoring.enabled
            
            if old_enabled != new_enabled:
                impact['severity'] = 'medium'
                impact['description'] = f"Weighted scoring {'enabled' if new_enabled else 'disabled'}"
                impact['affects_running_operations'] = True
        
        elif section == 'progress_tracking':
            old_enabled = old_config.progress_tracking.enabled
            new_enabled = new_config.progress_tracking.enabled
            
            if old_enabled != new_enabled:
                impact['severity'] = 'low'
                impact['description'] = f"Progress tracking {'enabled' if new_enabled else 'disabled'}"
        
        return impact
    
    def _check_configuration_conflicts(self, config: IntegratedConfiguration) -> List[str]:
        """
        Check for configuration conflicts.
        
        Args:
            config: Configuration to check
            
        Returns:
            List of conflict descriptions
        """
        conflicts = []
        
        # Check if semantic mapping is disabled but case-specific mappings are enabled
        if not config.semantic_mapping.enabled and config.semantic_mapping.case_specific.get('enabled', False):
            conflicts.append("Case-specific semantic mappings are enabled but global semantic mapping is disabled")
        
        # Check if weighted scoring is disabled but case-specific scoring is enabled
        if not config.weighted_scoring.enabled and config.weighted_scoring.case_specific.get('enabled', False):
            conflicts.append("Case-specific scoring is enabled but global weighted scoring is disabled")
        
        # Check progress tracking frequency
        if config.progress_tracking.enabled and config.progress_tracking.update_frequency_ms < 100:
            conflicts.append("Very high progress update frequency may impact performance")
        
        return conflicts


# Global configuration change handler instance
_global_change_handler = None


def get_configuration_change_handler() -> ConfigurationChangeHandler:
    """
    Get the global configuration change handler instance.
    
    Returns:
        ConfigurationChangeHandler instance
    """
    global _global_change_handler
    if _global_change_handler is None:
        _global_change_handler = ConfigurationChangeHandler()
    return _global_change_handler


def register_configuration_listener(section: str, callback: Callable[[ConfigurationChangeEvent], None]):
    """
    Register a global configuration change listener.
    
    Args:
        section: Configuration section to listen for
        callback: Function to call when configuration changes
    """
    handler = get_configuration_change_handler()
    handler.register_listener(section, callback)


def unregister_configuration_listener(section: str, callback: Callable):
    """
    Unregister a global configuration change listener.
    
    Args:
        section: Configuration section
        callback: Callback function to remove
    """
    handler = get_configuration_change_handler()
    handler.unregister_listener(section, callback)


def notify_configuration_change(old_config: IntegratedConfiguration, new_config: IntegratedConfiguration):
    """
    Notify all listeners of a configuration change.
    
    Args:
        old_config: Previous configuration
        new_config: New configuration
    """
    handler = get_configuration_change_handler()
    handler.handle_configuration_change(old_config, new_config)