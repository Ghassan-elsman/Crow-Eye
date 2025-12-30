"""
Configuration Manager for Crow Eye Correlation Engine
Centralized singleton for managing feather, wing, and pipeline configurations with persistence.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

from PyQt5.QtCore import QObject, pyqtSignal


logger = logging.getLogger(__name__)


class ConfigurationManager(QObject):
    """Singleton configuration manager with signal-based notifications"""
    
    _instance = None
    _initialized = False
    
    # Signals for configuration changes
    feather_added = pyqtSignal(dict)  # Emits feather metadata
    feather_removed = pyqtSignal(str)  # Emits feather_id
    wing_added = pyqtSignal(str)  # Emits wing file path
    wing_removed = pyqtSignal(str)  # Emits wing file path
    pipeline_added = pyqtSignal(str)  # Emits pipeline file path
    pipeline_removed = pyqtSignal(str)  # Emits pipeline file path
    configurations_loaded = pyqtSignal()  # Emits when all configs loaded
    
    def __new__(cls):
        """Ensure singleton instance"""
        if cls._instance is None:
            cls._instance = super(ConfigurationManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize configuration manager (only once)"""
        if ConfigurationManager._initialized:
            return
        
        super().__init__()
        
        self.case_root = None
        self.correlation_dir = None
        self.feathers_dir = None
        self.wings_dir = None
        self.pipelines_dir = None
        self.config_file = None
        
        self.feathers_registry = {}  # feather_id -> metadata dict
        self.wings_list = []  # List of wing file paths
        self.pipelines_list = []  # List of pipeline file paths
        
        ConfigurationManager._initialized = True
        logger.info("[ConfigManager] Initialized")
    
    @classmethod
    def get_instance(cls) -> 'ConfigurationManager':
        """Get singleton instance"""
        if cls._instance is None:
            cls._instance = ConfigurationManager()
        return cls._instance
    
    def set_case_directory(self, case_root: str) -> None:
        """
        Set current case directory and create structure.
        
        Args:
            case_root: Path to case root directory
        """
        self.case_root = Path(case_root)
        self.correlation_dir = self.case_root / "Correlation"
        self.feathers_dir = self.correlation_dir / "feathers"
        self.wings_dir = self.correlation_dir / "wings"
        self.pipelines_dir = self.correlation_dir / "pipelines"
        self.config_file = self.correlation_dir / "config.json"
        
        logger.info(f"[ConfigManager] Case directory set: {case_root}")
        
        # Create directory structure
        self.create_directory_structure()
    
    def get_correlation_directory(self) -> str:
        """Get path to Correlation directory"""
        if self.correlation_dir:
            return str(self.correlation_dir)
        return ""
    
    def create_directory_structure(self) -> bool:
        """
        Create Correlation directory structure.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Create main correlation directory
            self.correlation_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"[ConfigManager] Created directory: {self.correlation_dir}")
            
            # Create subdirectories
            self.feathers_dir.mkdir(exist_ok=True)
            logger.info(f"[ConfigManager] Created directory: {self.feathers_dir}")
            
            self.wings_dir.mkdir(exist_ok=True)
            logger.info(f"[ConfigManager] Created directory: {self.wings_dir}")
            
            self.pipelines_dir.mkdir(exist_ok=True)
            logger.info(f"[ConfigManager] Created directory: {self.pipelines_dir}")
            
            # Create results directory
            results_dir = self.correlation_dir / "results"
            results_dir.mkdir(exist_ok=True)
            logger.info(f"[ConfigManager] Created directory: {results_dir}")
            
            return True
            
        except Exception as e:
            logger.error(f"[ConfigManager] Error creating directory structure: {e}")
            return False
    
    def add_feather(self, feather_id: str, db_path: str, 
                   artifact_type: str, metadata: dict = None) -> bool:
        """
        Add feather to registry and emit signal.
        
        Args:
            feather_id: Unique identifier for feather
            db_path: Path to feather database file
            artifact_type: Type of artifact (MFT, Prefetch, etc.)
            metadata: Optional additional metadata
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Create feather metadata
            feather_metadata = {
                'feather_id': feather_id,
                'feather_name': feather_id,
                'artifact_type': artifact_type,
                'database_path': str(db_path),
                'created_date': datetime.now().isoformat(),
                'metadata': metadata or {}
            }
            
            # Add to registry
            self.feathers_registry[feather_id] = feather_metadata
            
            # Save registry
            if not self.save_feather_registry():
                logger.warning(f"[ConfigManager] Failed to save registry after adding feather: {feather_id}")
            
            # Emit signal
            self.feather_added.emit(feather_metadata)
            logger.info(f"[ConfigManager] Added feather: {feather_id} ({artifact_type})")
            
            return True
            
        except Exception as e:
            logger.error(f"[ConfigManager] Error adding feather: {e}")
            return False
    
    def remove_feather(self, feather_id: str) -> bool:
        """
        Remove feather from registry and emit signal.
        
        Args:
            feather_id: Unique identifier for feather
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if feather_id in self.feathers_registry:
                del self.feathers_registry[feather_id]
                
                # Save registry
                self.save_feather_registry()
                
                # Emit signal
                self.feather_removed.emit(feather_id)
                logger.info(f"[ConfigManager] Removed feather: {feather_id}")
                
                return True
            else:
                logger.warning(f"[ConfigManager] Feather not found: {feather_id}")
                return False
                
        except Exception as e:
            logger.error(f"[ConfigManager] Error removing feather: {e}")
            return False
    
    def get_all_feathers(self) -> List[dict]:
        """Get all registered feathers"""
        return list(self.feathers_registry.values())
    
    def get_feather_by_id(self, feather_id: str) -> Optional[dict]:
        """Get specific feather metadata"""
        return self.feathers_registry.get(feather_id)
    
    def load_wings(self) -> List[str]:
        """
        Scan wings directory and return list of wing file paths.
        
        Returns:
            List of wing file paths
        """
        try:
            if not self.wings_dir or not self.wings_dir.exists():
                logger.warning("[ConfigManager] Wings directory not found")
                return []
            
            wing_files = list(self.wings_dir.glob("*.json"))
            self.wings_list = [str(f) for f in wing_files]
            
            logger.info(f"[ConfigManager] Loaded {len(self.wings_list)} wings")
            return self.wings_list
            
        except Exception as e:
            logger.error(f"[ConfigManager] Error loading wings: {e}")
            return []
    
    def load_pipelines(self) -> List[str]:
        """
        Scan pipelines directory and return list of pipeline file paths.
        
        Returns:
            List of pipeline file paths
        """
        try:
            if not self.pipelines_dir or not self.pipelines_dir.exists():
                logger.warning("[ConfigManager] Pipelines directory not found")
                return []
            
            pipeline_files = list(self.pipelines_dir.glob("*.json"))
            self.pipelines_list = [str(f) for f in pipeline_files]
            
            logger.info(f"[ConfigManager] Loaded {len(self.pipelines_list)} pipelines")
            return self.pipelines_list
            
        except Exception as e:
            logger.error(f"[ConfigManager] Error loading pipelines: {e}")
            return []
    
    def load_all_configurations(self) -> Tuple[List[dict], List[str], List[str]]:
        """
        Load all configurations and emit loaded signal.
        
        Returns:
            Tuple of (feathers, wings, pipelines)
        """
        try:
            logger.info("[ConfigManager] Loading all configurations...")
            
            # Load feather registry
            self._load_feather_registry()
            
            # Load wings
            wings = self.load_wings()
            
            # Load pipelines
            pipelines = self.load_pipelines()
            
            # Emit loaded signal
            self.configurations_loaded.emit()
            
            logger.info(f"[ConfigManager] Loaded {len(self.feathers_registry)} feathers, "
                       f"{len(wings)} wings, {len(pipelines)} pipelines")
            
            return (self.get_all_feathers(), wings, pipelines)
            
        except Exception as e:
            logger.error(f"[ConfigManager] Error loading configurations: {e}")
            return ([], [], [])
    
    def _load_feather_registry(self) -> bool:
        """
        Load feather metadata registry from config.json.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            if not self.config_file or not self.config_file.exists():
                logger.info("[ConfigManager] No config.json found, starting fresh")
                self.feathers_registry = {}
                return True
            
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            
            # Validate version
            version = config_data.get('version', '1.0')
            if version != '1.0':
                logger.warning(f"[ConfigManager] Config version {version} may not be compatible")
            
            # Load feathers
            feathers = config_data.get('feathers', [])
            self.feathers_registry = {}
            
            for feather_data in feathers:
                feather_id = feather_data.get('feather_id')
                if feather_id:
                    # Validate database file exists
                    db_path = feather_data.get('database_path')
                    if db_path and os.path.exists(db_path):
                        self.feathers_registry[feather_id] = feather_data
                    else:
                        logger.warning(f"[ConfigManager] Feather database not found: {db_path}")
            
            logger.info(f"[ConfigManager] Loaded {len(self.feathers_registry)} feathers from registry")
            return True
            
        except json.JSONDecodeError as e:
            logger.error(f"[ConfigManager] Corrupted config.json: {e}")
            logger.info("[ConfigManager] Starting with fresh configuration")
            self.feathers_registry = {}
            return False
            
        except Exception as e:
            logger.error(f"[ConfigManager] Error loading feather registry: {e}")
            self.feathers_registry = {}
            return False
    
    def save_feather_registry(self) -> bool:
        """
        Save feather metadata registry to config.json.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            if not self.config_file:
                logger.error("[ConfigManager] Config file path not set")
                return False
            
            # Prepare config data
            config_data = {
                'version': '1.0',
                'case_root': str(self.case_root) if self.case_root else '',
                'created_date': datetime.now().isoformat(),
                'last_modified': datetime.now().isoformat(),
                'feathers': list(self.feathers_registry.values())
            }
            
            # Write to file with atomic operation
            temp_file = self.config_file.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)
            
            # Atomic rename
            temp_file.replace(self.config_file)
            
            logger.info(f"[ConfigManager] Saved {len(self.feathers_registry)} feathers to registry")
            return True
            
        except Exception as e:
            logger.error(f"[ConfigManager] Error saving feather registry: {e}")
            return False
    
    def validate_configuration(self, config_type: str, 
                              config_data: dict) -> Tuple[bool, List[str]]:
        """
        Validate configuration structure and references.
        
        Args:
            config_type: Type of configuration ('feather', 'wing', 'pipeline')
            config_data: Configuration data to validate
            
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []
        
        try:
            if config_type == 'feather':
                # Validate feather metadata
                required_fields = ['feather_id', 'artifact_type', 'database_path']
                for field in required_fields:
                    if field not in config_data:
                        errors.append(f"Missing required field: {field}")
                
                # Validate database path exists
                db_path = config_data.get('database_path')
                if db_path and not os.path.exists(db_path):
                    errors.append(f"Database file not found: {db_path}")
            
            elif config_type == 'wing':
                # Validate wing configuration
                required_fields = ['wing_name', 'source_database', 'feather_output']
                for field in required_fields:
                    if field not in config_data:
                        errors.append(f"Missing required field: {field}")
            
            elif config_type == 'pipeline':
                # Validate pipeline configuration
                required_fields = ['pipeline_name', 'feather_configs']
                for field in required_fields:
                    if field not in config_data:
                        errors.append(f"Missing required field: {field}")
            
            else:
                errors.append(f"Unknown configuration type: {config_type}")
            
        except Exception as e:
            errors.append(f"Validation error: {str(e)}")
        
        return (len(errors) == 0, errors)
