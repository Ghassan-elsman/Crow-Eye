"""
Configuration Migration Utilities

Provides utilities for migrating existing configurations to new formats,
ensuring backward compatibility and smooth transitions.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime

logger = logging.getLogger(__name__)


class ConfigurationMigration:
    """Handles migration of configuration files to new formats"""
    
    @staticmethod
    def migrate_integrated_config(config_path: Path) -> bool:
        """
        Migrate integrated configuration to use artifact type registry.
        
        Args:
            config_path: Path to integrated configuration file
            
        Returns:
            True if migration was successful or not needed, False on error
        """
        try:
            if not config_path.exists():
                logger.info(f"Configuration file not found: {config_path}")
                return True  # Nothing to migrate
            
            # Load existing configuration
            with open(config_path, 'r') as f:
                config_data = json.load(f)
            
            # Check if migration is needed
            needs_migration = False
            
            # Check weighted scoring configuration
            if 'weighted_scoring' in config_data:
                scoring = config_data['weighted_scoring']
                if 'default_weights' in scoring:
                    # Configuration already has weights, no migration needed
                    logger.info("Configuration already has default_weights, no migration needed")
                else:
                    needs_migration = True
            
            if not needs_migration:
                logger.info("Configuration is up to date, no migration needed")
                return True
            
            # Perform migration
            logger.info(f"Migrating configuration: {config_path}")
            
            # Add default weights from registry if missing
            if 'weighted_scoring' in config_data:
                if 'default_weights' not in config_data['weighted_scoring']:
                    try:
                        from .artifact_type_registry import get_registry
                        registry = get_registry()
                        config_data['weighted_scoring']['default_weights'] = registry.get_default_weights_dict()
                        logger.info("Added default_weights from artifact type registry")
                    except Exception as e:
                        logger.warning(f"Could not load weights from registry: {e}")
            
            # Update last_modified timestamp
            if 'last_modified' in config_data:
                config_data['last_modified'] = datetime.now().isoformat()
            
            # Add migration marker
            if 'migration_history' not in config_data:
                config_data['migration_history'] = []
            
            config_data['migration_history'].append({
                'version': '2.1.0',
                'date': datetime.now().isoformat(),
                'description': 'Migrated to use artifact type registry'
            })
            
            # Backup original file
            backup_path = config_path.with_suffix('.json.backup')
            if not backup_path.exists():
                with open(backup_path, 'w') as f:
                    json.dump(config_data, f, indent=2)
                logger.info(f"Created backup: {backup_path}")
            
            # Save migrated configuration
            with open(config_path, 'w') as f:
                json.dump(config_data, f, indent=2)
            
            logger.info(f"Successfully migrated configuration: {config_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to migrate configuration {config_path}: {e}")
            return False
    
    @staticmethod
    def migrate_wing_config(wing_config_path: Path) -> bool:
        """
        Migrate wing configuration to use artifact type registry.
        
        Args:
            wing_config_path: Path to wing configuration file
            
        Returns:
            True if migration was successful or not needed, False on error
        """
        try:
            if not wing_config_path.exists():
                logger.info(f"Wing configuration file not found: {wing_config_path}")
                return True  # Nothing to migrate
            
            # Load existing configuration
            with open(wing_config_path, 'r') as f:
                wing_data = json.load(f)
            
            # Check if migration is needed
            needs_migration = False
            
            # Check anchor_priority
            if 'anchor_priority' not in wing_data or not wing_data['anchor_priority']:
                needs_migration = True
            
            if not needs_migration:
                logger.info("Wing configuration is up to date, no migration needed")
                return True
            
            # Perform migration
            logger.info(f"Migrating wing configuration: {wing_config_path}")
            
            # Add anchor_priority from registry if missing
            if 'anchor_priority' not in wing_data or not wing_data['anchor_priority']:
                try:
                    from .artifact_type_registry import get_registry
                    registry = get_registry()
                    wing_data['anchor_priority'] = registry.get_anchor_priority_list()
                    logger.info("Added anchor_priority from artifact type registry")
                except Exception as e:
                    logger.warning(f"Could not load anchor_priority from registry: {e}")
            
            # Update last_modified timestamp
            if 'last_modified' in wing_data:
                wing_data['last_modified'] = datetime.now().isoformat()
            
            # Save migrated configuration
            with open(wing_config_path, 'w') as f:
                json.dump(wing_data, f, indent=2)
            
            logger.info(f"Successfully migrated wing configuration: {wing_config_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to migrate wing configuration {wing_config_path}: {e}")
            return False
    
    @staticmethod
    def migrate_all_configurations(config_directory: Path) -> Dict[str, Any]:
        """
        Migrate all configurations in a directory.
        
        Args:
            config_directory: Root configuration directory
            
        Returns:
            Dictionary with migration results
        """
        results = {
            'total_files': 0,
            'migrated': 0,
            'skipped': 0,
            'failed': 0,
            'errors': []
        }
        
        try:
            # Migrate integrated configuration
            integrated_config = config_directory / "integrated_config.json"
            if integrated_config.exists():
                results['total_files'] += 1
                if ConfigurationMigration.migrate_integrated_config(integrated_config):
                    results['migrated'] += 1
                else:
                    results['failed'] += 1
                    results['errors'].append(f"Failed to migrate {integrated_config}")
            
            # Migrate wing configurations
            wings_dir = config_directory / "wings"
            if wings_dir.exists():
                for wing_file in wings_dir.glob("*.json"):
                    results['total_files'] += 1
                    if ConfigurationMigration.migrate_wing_config(wing_file):
                        results['migrated'] += 1
                    else:
                        results['failed'] += 1
                        results['errors'].append(f"Failed to migrate {wing_file}")
            
            logger.info(f"Migration complete: {results['migrated']}/{results['total_files']} files migrated")
            
        except Exception as e:
            logger.error(f"Failed to migrate configurations: {e}")
            results['errors'].append(str(e))
        
        return results
    
    @staticmethod
    def check_migration_needed(config_path: Path) -> bool:
        """
        Check if a configuration file needs migration.
        
        Args:
            config_path: Path to configuration file
            
        Returns:
            True if migration is needed, False otherwise
        """
        try:
            if not config_path.exists():
                return False
            
            with open(config_path, 'r') as f:
                config_data = json.load(f)
            
            # Check for migration markers
            if 'migration_history' in config_data:
                # Check if already migrated to 2.1.0
                for migration in config_data['migration_history']:
                    if migration.get('version') == '2.1.0':
                        return False
            
            # Check if configuration has new format
            if 'weighted_scoring' in config_data:
                if 'default_weights' not in config_data['weighted_scoring']:
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to check migration status for {config_path}: {e}")
            return False


def migrate_on_startup(config_directory: str = "configs") -> bool:
    """
    Automatically migrate configurations on application startup.
    
    Args:
        config_directory: Root configuration directory
        
    Returns:
        True if migration was successful, False otherwise
    """
    try:
        config_dir = Path(config_directory)
        
        if not config_dir.exists():
            logger.info("Configuration directory does not exist, no migration needed")
            return True
        
        logger.info("Checking for configuration migrations...")
        
        # Check if migration is needed
        integrated_config = config_dir / "integrated_config.json"
        if ConfigurationMigration.check_migration_needed(integrated_config):
            logger.info("Configuration migration needed, starting migration...")
            results = ConfigurationMigration.migrate_all_configurations(config_dir)
            
            if results['failed'] > 0:
                logger.warning(f"Migration completed with {results['failed']} failures")
                for error in results['errors']:
                    logger.error(f"  {error}")
                return False
            else:
                logger.info("Configuration migration completed successfully")
                return True
        else:
            logger.info("No configuration migration needed")
            return True
            
    except Exception as e:
        logger.error(f"Failed to migrate configurations on startup: {e}")
        return False
