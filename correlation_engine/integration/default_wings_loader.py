"""
Default Wings Loader

Handles loading and initialization of default Wings for the Correlation Engine.
Provides utilities for copying default Wings to user configuration and registering them.
"""

import json
import logging
import shutil
from pathlib import Path
from typing import List, Optional

from ..config.wing_config import WingConfig

logger = logging.getLogger(__name__)


class DefaultWingsLoader:
    """
    Manages loading and initialization of default Wings.
    
    Default Wings are sophisticated pre-configured correlation rules that provide
    immediate value to users. They are stored in the integration/default_wings directory
    and can be copied to user configuration or case directories.
    """
    
    # Default Wings directory (relative to this file)
    DEFAULT_WINGS_DIR = Path(__file__).parent / "default_wings"
    
    # List of default Wing filenames
    DEFAULT_WING_FILES = [
        "Execution_Proof_Correlation.json",
        "User_Activity_Correlation.json"
    ]
    
    @classmethod
    def get_default_wings_directory(cls) -> Path:
        """
        Get the directory containing default Wings.
        
        Returns:
            Path to default Wings directory
        """
        return cls.DEFAULT_WINGS_DIR
    
    @classmethod
    def load_default_wing(cls, wing_filename: str) -> Optional[WingConfig]:
        """
        Load a default Wing configuration.
        
        Args:
            wing_filename: Filename of the Wing (e.g., "Execution_Proof_Correlation.json")
            
        Returns:
            WingConfig object or None if loading fails
        """
        wing_path = cls.DEFAULT_WINGS_DIR / wing_filename
        
        if not wing_path.exists():
            logger.error(f"Default Wing not found: {wing_path}")
            return None
        
        try:
            with open(wing_path, 'r') as f:
                wing_data = json.load(f)
            
            wing_config = WingConfig.from_dict(wing_data)
            logger.info(f"Loaded default Wing: {wing_config.wing_name}")
            return wing_config
            
        except Exception as e:
            logger.error(f"Failed to load default Wing {wing_filename}: {e}")
            return None
    
    @classmethod
    def load_all_default_wings(cls) -> List[WingConfig]:
        """
        Load all default Wings.
        
        Returns:
            List of WingConfig objects
        """
        wings = []
        
        for wing_file in cls.DEFAULT_WING_FILES:
            wing = cls.load_default_wing(wing_file)
            if wing:
                wings.append(wing)
        
        logger.info(f"Loaded {len(wings)} default Wings")
        return wings
    
    @classmethod
    def copy_default_wings_to_directory(cls, target_directory: Path, force_update: bool = False) -> List[Path]:
        """
        Copy default Wings to a target directory.
        
        Args:
            target_directory: Directory to copy Wings to
            force_update: If True, overwrite existing Wings with latest defaults
            
        Returns:
            List of paths to copied Wing files
        """
        target_directory.mkdir(parents=True, exist_ok=True)
        copied_files = []
        
        for wing_file in cls.DEFAULT_WING_FILES:
            source_path = cls.DEFAULT_WINGS_DIR / wing_file
            target_path = target_directory / wing_file
            
            # Copy if doesn't exist OR if force_update is True
            if not target_path.exists() or force_update:
                try:
                    shutil.copy2(source_path, target_path)
                    copied_files.append(target_path)
                    action = "Updated" if target_path.exists() and force_update else "Copied"
                    logger.info(f"{action} default Wing to: {target_path}")
                except Exception as e:
                    logger.error(f"Failed to copy {wing_file}: {e}")
            else:
                logger.debug(f"Default Wing already exists, skipping: {target_path}")
        
        return copied_files
    
    @classmethod
    def force_update_case_wings(cls, case_correlation_dir: Path) -> List[Path]:
        """
        Force update case's Wings directory with latest default Wings.
        
        This overwrites existing Wings with the latest defaults.
        Use when default Wings have been updated with new feathers.
        
        Args:
            case_correlation_dir: Case's Correlation directory
            
        Returns:
            List of paths to updated Wing files
        """
        wings_dir = case_correlation_dir / "wings"
        logger.info(f"Force updating Wings in: {wings_dir}")
        return cls.copy_default_wings_to_directory(wings_dir, force_update=True)
    
    @classmethod
    def initialize_user_wings_directory(cls, user_config_dir: Path) -> List[Path]:
        """
        Initialize user's Wings directory with default Wings.
        
        This is typically called on first run or when setting up a new user.
        
        Args:
            user_config_dir: User's configuration directory (e.g., ~/.crow_eye)
            
        Returns:
            List of paths to initialized Wing files
        """
        wings_dir = user_config_dir / "wings"
        return cls.copy_default_wings_to_directory(wings_dir)
    
    @classmethod
    def initialize_case_wings_directory(cls, case_correlation_dir: Path) -> List[Path]:
        """
        Initialize case's Wings directory with default Wings.
        
        This is typically called when opening a new case.
        
        Args:
            case_correlation_dir: Case's Correlation directory
            
        Returns:
            List of paths to initialized Wing files
        """
        wings_dir = case_correlation_dir / "wings"
        return cls.copy_default_wings_to_directory(wings_dir)
    
    @classmethod
    def get_default_wing_info(cls) -> List[dict]:
        """
        Get information about all default Wings without loading them fully.
        
        Returns:
            List of dictionaries with Wing metadata
        """
        wing_info = []
        
        for wing_file in cls.DEFAULT_WING_FILES:
            wing_path = cls.DEFAULT_WINGS_DIR / wing_file
            
            if wing_path.exists():
                try:
                    with open(wing_path, 'r') as f:
                        wing_data = json.load(f)
                    
                    wing_info.append({
                        'filename': wing_file,
                        'wing_name': wing_data.get('wing_name', 'Unknown'),
                        'wing_id': wing_data.get('wing_id', 'unknown'),
                        'description': wing_data.get('description', ''),
                        'proves': wing_data.get('proves', ''),
                        'feather_count': len(wing_data.get('feathers', [])),
                        'semantic_rules_count': len(wing_data.get('semantic_rules', [])),
                        'use_weighted_scoring': wing_data.get('use_weighted_scoring', False)
                    })
                except Exception as e:
                    logger.error(f"Failed to read Wing info from {wing_file}: {e}")
        
        return wing_info
    
    @classmethod
    def validate_default_wings(cls) -> bool:
        """
        Validate that all default Wings are present and loadable.
        
        Returns:
            True if all Wings are valid, False otherwise
        """
        all_valid = True
        
        for wing_file in cls.DEFAULT_WING_FILES:
            wing = cls.load_default_wing(wing_file)
            if wing is None:
                logger.error(f"Default Wing validation failed: {wing_file}")
                all_valid = False
            else:
                logger.info(f"✓ Default Wing validated: {wing.wing_name}")
        
        return all_valid


def initialize_default_wings_on_startup(user_config_dir: Path) -> List[WingConfig]:
    """
    Initialize default Wings on application startup.
    
    This function should be called when the application starts to ensure
    default Wings are available in the user's configuration directory.
    
    Args:
        user_config_dir: User's configuration directory
        
    Returns:
        List of loaded WingConfig objects
    """
    logger.info("Initializing default Wings on startup")
    
    # Copy default Wings to user config if needed
    DefaultWingsLoader.initialize_user_wings_directory(user_config_dir)
    
    # Load all default Wings
    wings = DefaultWingsLoader.load_all_default_wings()
    
    logger.info(f"Default Wings initialization complete: {len(wings)} Wings available")
    return wings


def get_default_wings_for_case(case_correlation_dir: Path) -> List[WingConfig]:
    """
    Get default Wings for a case.
    
    This function copies default Wings to the case directory if needed,
    then loads them.
    
    Args:
        case_correlation_dir: Case's Correlation directory
        
    Returns:
        List of loaded WingConfig objects
    """
    logger.info(f"Getting default Wings for case: {case_correlation_dir}")
    
    # Copy default Wings to case if needed
    DefaultWingsLoader.initialize_case_wings_directory(case_correlation_dir)
    
    # Load Wings from case directory
    wings_dir = case_correlation_dir / "wings"
    wings = []
    
    for wing_file in DefaultWingsLoader.DEFAULT_WING_FILES:
        wing_path = wings_dir / wing_file
        if wing_path.exists():
            try:
                wing = WingConfig.load_from_file(str(wing_path))
                wings.append(wing)
            except Exception as e:
                logger.error(f"Failed to load Wing from {wing_path}: {e}")
    
    logger.info(f"Loaded {len(wings)} default Wings for case")
    return wings
